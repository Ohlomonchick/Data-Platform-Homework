from __future__ import annotations

import logging
import pendulum

from onetl.connection import SparkHDFS, Hive
from airflow.models.dag import DAG
from airflow.operators.python import PythonOperator
from pyspark.sql import functions as F
from pyspark.sql import SparkSession

from onetl.file import FileDFReader
from onetl.file.format import CSV

from onetl.db import DBWriter 

with DAG(
    "Transform_Titanic",
    start_date=pendulum.datetime(2025, 3, 21, tz="UTC"),
    catchup=False,
    schedule=None,
    tags=["example"],
) as dag:
    local_data_path = "/home/hadoop/input/data.csv"


    def transform_data():
        spark = SparkSession.builder \
            .master("yarn") \
            .appName("spark-with-yarn") \
            .config("spark.sql.warehouse.dir", "hdfs://tmpl-nn:9000/user/hive/warehouse") \
            .config("spark.hive.metastore.uris", "thrift://tmpl-jn:9083") \
            .enableHiveSupport() \
            .getOrCreate()

        hdfs = SparkHDFS(host="tmpl-nn", port=9000, spark=spark, cluster="test")
        reader = FileDFReader(connection=hdfs, format=CSV(delimiter=",", header=True), source_path="/input")
        df = reader.run(["titanic.csv"])
        hive = Hive(spark=spark, cluster="test")
        writer = DBWriter(connection=hive, table="test.spark_partitions", options={"if_exists": "replace_entire_table"})
        writer.run(df)

        df = df.withColumnRenamed("Siblings/Spouses Aboard", "SibSp") \
            .withColumnRenamed("Parents/Children Aboard", "Parch") \
                .withColumnRenamed("Fare\r", "Fare")

        df = df.withColumn("Survived", F.col("Survived").cast("integer")) \
            .withColumn("Age", F.col("Age").cast("double")) \
            .withColumn("Fare", F.col("Fare").cast("double"))

        logging.info(df.head())
        (df.write
        .partitionBy("Pclass")
        .mode("overwrite")
        .saveAsTable("test.spark_partitions"))

    transform_task = PythonOperator(task_id="transform_task", python_callable=transform_data)
    transform_task