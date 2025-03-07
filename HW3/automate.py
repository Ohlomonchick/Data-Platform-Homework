import os
import paramiko
import time

TEAM_HOST = "176.109.91.34"     # Адрес jump-сервера
TEAM_USER = "team"             # Имя пользователя для SSH на jump-сервер
TEAM_PASSWORD = os.environ.get("TEAM_PASSWORD", 's_JDal9K4iF`')  # Пароль для jump-сервера (используется при sudo)
HADOOP_PASSWORD = os.environ.get("HADOOP_PASSWORD", 'Dimonchick228')   # Пароль для пользователя hadoop
PRIVATE_KEY_PATH = "C:/Users/Dmitry/.ssh/id_rsa"
JUMP_NODE_IP = '192.168.1.142'

# Путь к локальным файлам, которые нужно отправить на jump
LOCAL_HIVE_SITE = "hive-site.xml"

# Папка на jump-сервере, куда мы временно складываем конфиги
REMOTE_TMP_DIR = f"/tmp_configs"

# Список адресов нод (имена/алиасы должны резолвиться на jump-сервере. Замените на те, что указаны у вас)
NODES = {
    "tmpl-nn": "tmpl-nn",
    "tmpl-dn-00": "tmpl-dn-00",
    "tmpl-dn-01": "tmpl-dn-01"
}


# Папка на jump-сервере, куда мы временно складываем конфиги
REMOTE_TMP_DIR = f"/tmp_configs"

# Список адресов нод (имена/алиасы должны резолвиться на jump-сервере. Замените на те, что указаны у вас)
NODES = {
    "tmpl-nn": "tmpl-nn",
    "tmpl-dn-00": "tmpl-dn-00",
    "tmpl-dn-01": "tmpl-dn-01"
}


def run_command(ssh_client, command, use_sudo=False, print_output=True):
    """
    Executes a command on a remote SSH client with exec_command.
    If `use_sudo` is True, it will prepend `echo <TEAM_PASSWORD> | sudo -S`.
    """
    if use_sudo:
        command = f"echo '{TEAM_PASSWORD}' | sudo -S -p '' {command}"

    stdin, stdout, stderr = ssh_client.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()

    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")

    if print_output:
        print(f"COMMAND: {command}")
        print(f"EXIT CODE: {exit_code}")
        if out:
            print("--- STDOUT ---")
            print(out)
        if err:
            print("--- STDERR ---")
            print(err)

    return exit_code, out, err


def open_interactive_shell(ssh_client):
    """
    Opens an interactive shell channel on the existing Paramiko SSHClient session.
    Returns the channel object (invoke_shell).
    """
    shell = ssh_client.invoke_shell()
    time.sleep(1)  # Give the shell a moment to initialize
    # Drain any initial welcome message or prompts
    if shell.recv_ready():
        shell.recv(9999)
    return shell


def run_shell_command_in_shell(shell, cmd, wait=1.0, exit_code=True):
    """
    Sends a command to an existing shell and waits 'wait' seconds,
    then reads and returns whatever is in the buffer.
    """
    cmd_with_exit = f'{cmd}; echo "EXITCODE:$?"' if exit_code else cmd
    shell.send(cmd_with_exit + "\n")
    time.sleep(wait)
    output = ""
    while shell.recv_ready():
        output_part = shell.recv(9999).decode("utf-8", errors="ignore")
        output += output_part
    # For debugging, you can uncomment:
    # print(f"[SHELL CMD]: {cmd}")
    # print(f"[SHELL OUTPUT]: {output}")
    return output



def main():
    # Подключаемся к jump-серверу как team
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    private_key = paramiko.RSAKey(filename=PRIVATE_KEY_PATH)

    print(f"[*] Connecting to jump server {TEAM_HOST} as {TEAM_USER}...")
    ssh.connect(TEAM_HOST, username=TEAM_USER, pkey=private_key)
    print("[+] Connected to jump-server.")

    # Создадим временную директорию на jump (на всякий случай)
    run_command(ssh, f"mkdir -p {REMOTE_TMP_DIR}", use_sudo=True)
    run_command(ssh, f"chmod 777 {REMOTE_TMP_DIR}", use_sudo=True)

    # Откроем интерактивный шелл для дальнейших команд
    shell = open_interactive_shell(ssh)

    # Переходим в пользователя hadoop (только с hadoop можно ходить по нодам)
    run_shell_command_in_shell(shell, f"echo '{TEAM_PASSWORD}' | sudo -S -p '' -i -u hadoop", wait=2)

    # Переходим на tmpl-nn
    run_shell_command_in_shell(shell, f"ssh -o StrictHostKeyChecking=no {NODES['tmpl-nn']}", wait=2)

    # Устанавливаем PostgreSQL
    run_shell_command_in_shell(shell, f"echo '{TEAM_PASSWORD}' | su team", wait=2)
    run_shell_command_in_shell(shell, f"echo '{TEAM_PASSWORD}' | sudo -S apt-get update -y", wait=2)
    run_shell_command_in_shell(shell, f"sudo -S apt-get install -y postgresql", wait=3)

   # Создаём БД metastore, пользователя hive и даём ему права
    psql_commands = [
        "CREATE DATABASE metastore;",
        "CREATE USER hive WITH PASSWORD 'hiveMegaPass';",
        "GRANT ALL PRIVILEGES ON DATABASE metastore TO hive;",
        "ALTER DATABASE metastore OWNER TO hive;"
    ]
    run_shell_command_in_shell(shell, "sudo -i -u postgres")
    for cmd in psql_commands:
        run_shell_command_in_shell(
            shell,
            cmd,
            wait=1,
            exit_code=False
        )

    # Разрешаем удалённые подключения в pg_hba.conf и postgresql.conf
    run_shell_command_in_shell(shell, f"echo '{TEAM_PASSWORD}' | su team", wait=2)
    run_shell_command_in_shell(shell,
        "echo \"host    metastore       hive    192.168.1.1/32       password\" | "
        f"echo '{TEAM_PASSWORD}' | sudo -S tee -a /etc/postgresql/16/main/pg_hba.conf",
        wait=1
    )
    run_shell_command_in_shell(shell,
        f"echo \"host    metastore       hive    {JUMP_NODE_IP}/32     password\" | "
        "sudo -S tee -a /etc/postgresql/16/main/pg_hba.conf",
        wait=1
    )
    # postgresql.conf
    run_shell_command_in_shell(shell,
        "echo \"listen_addresses = '*'\" | "
        f"sudo -S tee -a /etc/postgresql/16/main/postgresql.conf",
        wait=1
    )

    # Перезапускаем PostgreSQL
    run_shell_command_in_shell(shell, f"sudo -S systemctl restart postgresql", wait=2)

    # Выходим с tmpl-nn обратно на jump-ноду
    run_shell_command_in_shell(shell, "exit", wait=1)

    # Скачиваем Hive
    run_shell_command_in_shell(shell,
       "wget https://archive.apache.org/dist/hive/hive-4.0.0-alpha-2/"
       "apache-hive-4.0.0-alpha-2-bin.tar.gz -P /home/hadoop",
       wait=2
    )
    run_shell_command_in_shell(shell,
       "cd /home/hadoop && tar -xzvf apache-hive-4.0.0-alpha-2-bin.tar.gz",
       wait=10
    )

    run_shell_command_in_shell(shell,
       "cd /home/hadoop/apache-hive-4.0.0-alpha-2-bin/lib && "
       "wget https://jdbc.postgresql.org/download/postgresql-42.7.4.jar",
       wait=5
    )

    # Копируем на jump-сервер
    sftp = ssh.open_sftp()
    remote_hive_site = REMOTE_TMP_DIR + "/hive-site.xml"
    sftp.put(LOCAL_HIVE_SITE, remote_hive_site)
    sftp.close()

    # Теперь из интерактивного shell под hadoop скопируем в папку Hive
    run_shell_command_in_shell(shell,
       f"cp {remote_hive_site} /home/hadoop/apache-hive-4.0.0-alpha-2-bin/conf/hive-site.xml",
       wait=1
    )

    # Добавляем переменные окружения в ~/.profile
    profile_cmds = [
      "echo 'export HIVE_HOME=/home/hadoop/apache-hive-4.0.0-alpha-2-bin' >> ~/.profile",
      "echo 'export HIVE_CONF_DIR=$HIVE_HOME/conf' >> ~/.profile",
      "echo 'export HIVE_AUX_JARS_PATH=$HIVE_HOME/lib/*' >> ~/.profile",
      "echo 'export PATH=$PATH:$HIVE_HOME/bin' >> ~/.profile"
    ]
    for cmd in profile_cmds:
        run_shell_command_in_shell(shell, cmd, wait=0.5)

    # Применим изменения
    run_shell_command_in_shell(shell, "source ~/.profile", wait=1)

    # Проверяем установку Hive
    out = run_shell_command_in_shell(shell, "hive --version", wait=3)
    print("[DEBUG] hive --version output:\n", out)


    # Создадим папки /tmp и /user/hive/warehouse, дадим права
    run_shell_command_in_shell(shell, "hdfs dfs -mkdir /tmp", wait=1)
    run_shell_command_in_shell(shell, "hdfs dfs -mkdir -p /user/hive/warehouse", wait=1)
    run_shell_command_in_shell(shell, "hdfs dfs -chmod g+w /user/hive/warehouse", wait=1)
    run_shell_command_in_shell(shell, "hdfs dfs -chmod g+w /tmp", wait=1)

    # Инициализация схемы Hive в PostgreSQL (schematool)
    out_schema = run_shell_command_in_shell(
        shell,
        "cd /home/hadoop/apache-hive-4.0.0-alpha-2-bin && bin/schematool -dbType postgres -initSchema",
        wait=10
    )
    print("[DEBUG] schematool initSchema:\n", out_schema)

    # Запуск HiveServer2
    run_shell_command_in_shell(
        shell,
        "nohup hive --hiveconf hive.server2.enable.doAs=false "
        "--hiveconf hive.security.authorization.enable=false "
        "--service hiveserver2 1>> /tmp/hs2.log 2>> /tmp/hs2.log &",
        wait=3
    )
    print("[+] HiveServer2 started (logs in /tmp/hs2.log).")

    shell.close()
    ssh.close()

if __name__ == "__main__":
    main()