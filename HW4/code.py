from pyspark.sql import SparkSession

from pyspark.sql import functions as F

from onetl.connection import SparkHDFS, Hive

from onetl.file import FileDFReader
from onetl.file.format import CSV

from onetl.db import DBWriter 


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

df.count()

df.rdd.getNumPartitions()

hive = Hive(spark=spark, cluster="test")

writer = DBWriter(connection=hive, table="test.spark_partitions", options={"if_exists": "replace_entire_table"})