#!/usr/bin/env bash
set -e

# 1. Проверяем переменные окружения
if [[ -z "$TEAM_PASSWORD" || -z "$HADOOP_USER_PASSWORD" ]]; then
  echo "Ошибка: не заданы переменные TEAM_PASSWORD и/или HADOOP_USER_PASSWORD."
  echo "Пример использования:"
  echo "  TEAM_PASSWORD=\"pass_team\" HADOOP_USER_PASSWORD=\"pass_hadoop\" ./deploy-hadoop.sh"
  exit 1
fi

# 2. Переменные для IP и хостнеймов
JN_IP="192.168.1.142"
NN_IP="192.168.1.143"
DN1_IP="192.168.1.144"
DN2_IP="192.168.1.145"

JN_HOST="tmpl-jn"
NN_HOST="tmpl-nn"
DN1_HOST="tmpl-dn-00"
DN2_HOST="tmpl-dn-01"

ALL_NODES=("$JN_IP" "$NN_IP" "$DN1_IP" "$DN2_IP")
ALL_HOSTS=("$JN_HOST" "$NN_HOST" "$DN1_HOST" "$DN2_HOST")

# Hadoop дистрибутив
HADOOP_VERSION="3.4.0"
HADOOP_TARBALL="hadoop-${HADOOP_VERSION}.tar.gz"
HADOOP_URL="https://dlcdn.apache.org/hadoop/common/hadoop-${HADOOP_VERSION}/${HADOOP_TARBALL}"

# 3. Создаём пользователя hadoop на всех нодах и правим /etc/hosts
echo ">>> Создаем пользователя 'hadoop' на всех нодах и правим /etc/hosts..."

for i in "${!ALL_NODES[@]}"; do
  NODE="${ALL_NODES[$i]}"
  HOST="${ALL_HOSTS[$i]}"

  echo "==> Обработка ноды ${HOST} (${NODE})"

  # Создаем пользователя hadoop (без интерактивных вопросов)
  sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${NODE}" \
    "sudo adduser --disabled-password --gecos '' hadoop || true"

  # Задаём пароль пользователю hadoop
  sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${NODE}" \
    "echo 'hadoop:${HADOOP_USER_PASSWORD}' | sudo chpasswd"

  # Здесь для примера мы перезаписываем /etc/hosts нужными строками.
  sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${NODE}" bash <<EOF
    sudo bash -c 'cat > /etc/hosts' <<EOL
127.0.0.1 localhost
127.0.0.1 ${HOST}

${JN_IP}  ${JN_HOST}
${NN_IP}  ${NN_HOST}
${DN1_IP} ${DN1_HOST}
${DN2_IP} ${DN2_HOST}
EOL
EOF

done

# 4. Скачиваем Hadoop на JN-ноду и раскидываем на все узлы
echo ">>> Скачиваем hadoop-${HADOOP_VERSION} на JN и копируем на все ноды..."

# Скачиваем на tmpl-jn (локально, т.к. мы и так на jn, предположим)
wget -c "${HADOOP_URL}" -O "${HADOOP_TARBALL}"

# Раскидываем архив
for i in "${!ALL_NODES[@]}"; do
  NODE="${ALL_NODES[$i]}"
  HOST="${ALL_HOSTS[$i]}"
  if [[ "${NODE}" == "${JN_IP}" ]]; then
    echo "Узел ${HOST}: архив уже локально имеется."
  else
    echo "==> Копируем на ${HOST} (${NODE})"
    sshpass -p "$TEAM_PASSWORD" scp -o StrictHostKeyChecking=no "${HADOOP_TARBALL}" team@"${NODE}":/home/team/
    # Переносим файл пользователю hadoop
    sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${NODE}" \
      "sudo mv /home/team/${HADOOP_TARBALL} /home/hadoop/"
    sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${NODE}" \
      "sudo chown hadoop:hadoop /home/hadoop/${HADOOP_TARBALL}"
  fi
done

# 5. Распаковка Hadoop на каждой ноде
echo ">>> Распаковываем Hadoop на каждой ноде..."
for i in "${!ALL_NODES[@]}"; do
  NODE="${ALL_NODES[$i]}"
  echo "==> Распаковка на ноде ${NODE}"
  sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${NODE}" \
    "sudo -i -u hadoop tar -xzf /home/hadoop/${HADOOP_TARBALL} -C /home/hadoop/"
done

# 6. Настраиваем SSH-ключи для пользователя hadoop (делаем на jn, копируем остальным)
echo ">>> Генерация ssh-ключа для hadoop на jn и копирование остальным нодам..."
sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${JN_IP}" bash <<EOF
sudo -i -u hadoop bash -c '
  if [ ! -f /home/hadoop/.ssh/id_ed25519 ]; then
    mkdir -p /home/hadoop/.ssh
    chmod 700 /home/hadoop/.ssh
    ssh-keygen -t ed25519 -N "" -f /home/hadoop/.ssh/id_ed25519
    cat /home/hadoop/.ssh/id_ed25519.pub >> /home/hadoop/.ssh/authorized_keys
    chmod 600 /home/hadoop/.ssh/authorized_keys
  fi
'
EOF

# Теперь копируем .ssh с jn на остальные
for i in "${!ALL_NODES[@]}"; do
  NODE="${ALL_NODES[$i]}"
  HOST="${ALL_HOSTS[$i]}"

  if [[ "${NODE}" == "${JN_IP}" ]]; then
    continue
  fi

  echo "==> Копируем .ssh с jn на ${HOST}..."
  sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${JN_IP}" bash <<EOF
sudo -i -u hadoop scp -o StrictHostKeyChecking=no -r /home/hadoop/.ssh hadoop@${NODE}:/home/hadoop/
EOF
done


# 7. Добавляем переменные окружения в .profile на каждой ноде
echo ">>> Добавляем переменные окружения Hadoop и Java в .profile на каждой ноде..."

JAVA_HOME="/usr/lib/jvm/java-11-openjdk-amd64"
PROFILE_CONTENT=$(cat <<EOL
export HADOOP_HOME=/home/hadoop/hadoop-${HADOOP_VERSION}
export PATH=\$PATH:\$HADOOP_HOME/bin:\$HADOOP_HOME/sbin
export JAVA_HOME=${JAVA_HOME}
EOL
)

for i in "${!ALL_NODES[@]}"; do
  NODE="${ALL_NODES[$i]}"
  echo "==> Обновляем .profile на ноде ${NODE}"
  sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${NODE}" bash <<EOF
sudo -i -u hadoop bash -c '
  echo "${PROFILE_CONTENT}" >> /home/hadoop/.profile
  source /home/hadoop/.profile
'
EOF
done

# 8. Настраиваем основные конфиги hadoop-3.4.0/etc/hadoop
echo ">>> Создаем и рассылаем core-site.xml, hdfs-site.xml, workers, hadoop-env.sh..."

# Локально сформируем файлы во временной папке
TMP_DIR="$(mktemp -d)"

cat > "${TMP_DIR}/core-site.xml" <<EOF
<configuration>
  <property>
    <name>fs.default.name</name>
    <value>hdfs://${NN_HOST}:9000</value>
  </property>
</configuration>
EOF

cat > "${TMP_DIR}/hdfs-site.xml" <<EOF
<configuration>
  <property>
    <name>dfs.replication</name>
    <value>3</value>
  </property>
</configuration>
EOF

cat > "${TMP_DIR}/workers" <<EOF
${NN_HOST}
${DN1_HOST}
${DN2_HOST}
EOF

cat > "${TMP_DIR}/hadoop-env.sh" <<EOF
export JAVA_HOME=${JAVA_HOME}
EOF

# Рассылаем на все 4 ноды в /home/hadoop/hadoop-3.4.0/etc/hadoop
for i in "${!ALL_NODES[@]}"; do
  NODE="${ALL_NODES[$i]}"

  echo "==> Рассылка конфигов на ноду ${NODE}"
  sshpass -p "$TEAM_PASSWORD" scp -o StrictHostKeyChecking=no \
    "${TMP_DIR}/core-site.xml" \
    "${TMP_DIR}/hdfs-site.xml" \
    "${TMP_DIR}/workers" \
    "${TMP_DIR}/hadoop-env.sh" \
    team@"${NODE}":/home/team/

  sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${NODE}" bash <<EOF
    sudo mv /home/team/core-site.xml /home/hadoop/hadoop-${HADOOP_VERSION}/etc/hadoop/
    sudo mv /home/team/hdfs-site.xml /home/hadoop/hadoop-${HADOOP_VERSION}/etc/hadoop/
    sudo mv /home/team/workers /home/hadoop/hadoop-${HADOOP_VERSION}/etc/hadoop/
    sudo mv /home/team/hadoop-env.sh /home/hadoop/hadoop-${HADOOP_VERSION}/etc/hadoop/
    sudo chown hadoop:hadoop /home/hadoop/hadoop-${HADOOP_VERSION}/etc/hadoop/*.xml
    sudo chown hadoop:hadoop /home/hadoop/hadoop-${HADOOP_VERSION}/etc/hadoop/workers
    sudo chown hadoop:hadoop /home/hadoop/hadoop-${HADOOP_VERSION}/etc/hadoop/hadoop-env.sh
EOF

done

rm -rf "${TMP_DIR}"

# 9. Форматирование HDFS и запуск кластера (на nn)
echo ">>> Форматируем HDFS и запускаем кластер на NameNode (${NN_HOST})..."

sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${NN_IP}" bash <<EOF
sudo -i -u hadoop bash -c '
  cd /home/hadoop/hadoop-${HADOOP_VERSION}
  # Форматируем namenode
  echo ">>> Форматируем namenode..."
  yes Y | bin/hdfs namenode -format

  echo ">>> Запускаем HDFS..."
  sbin/start-dfs.sh
'
EOF

# 10. Простейшая проверка
echo ">>> Проверяем создание /test в HDFS..."
sshpass -p "$TEAM_PASSWORD" ssh -o StrictHostKeyChecking=no team@"${JN_IP}" bash <<EOF
sudo -i -u hadoop bash -c '
  hdfs dfs -mkdir /test
  hdfs dfs -ls /
'
EOF

echo ">>> Скрипт автоматической установки Hadoop завершён!"
