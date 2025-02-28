Ниже приведена пошаговая инструкция по развёртыванию YARN на кластере из 4 узлов с уже установленным Hadoop. Инструкция оформлена в Markdown, чтобы её можно было легко копировать и использовать.

---

# Развёртывание YARN на кластере Hadoop

## Общая информация

- **Кластер** состоит из 4 нод:
  - `192.168.1.142` (tmpl-jn)
  - `192.168.1.143` (tmpl-nn)
  - `192.168.1.144` (tmpl-dn-00)
  - `192.168.1.145` (tmpl-dn-01)
- **Пользователь:** `hadoop`  
  Пароль хранится в переменной окружения `HADOOP_ENV`.

> **Примечание:** Ниже используется IP-адрес jump-ноды `176.109.91.34`. Предполагается, что вы подключаетесь по SSH к этому серверу, используя команду вида:
> ```
> ssh -L <пробрасываемые_порты> <пользователь>@176.109.91.34
> ```

---

## 1. Пререквизиты

1. Убедитесь, что **Hadoop** уже установлен и файловая система HDFS отформатирована.
2. Проверьте, что **HDFS** запущен (namenode и datanode работают).

---

## 2. Настройка веб-интерфейса через Nginx (на Jump Node)

1. Скопируйте конфигурационный файл `nginx-def.conf` (это ваш заранее подготовленный конфиг) в путь `/etc/nginx/sites-available/default` на **jump node** (tmpl-jn).
   
   ```bash
   sudo cp nginx-def.conf /etc/nginx/sites-available/default
   ```

2. Перезапустите Nginx:
   
   ```bash
   sudo systemctl restart nginx
   ```

3. Пробросьте порт **9870** для доступа к веб-интерфейсу HDFS:
   
   ```bash
   ssh -L 9870:127.0.0.1:9870 176.109.91.34
   ```

---

## 3. Работа с HDFS

1. Войдите под пользователем `hadoop`:
   
   ```bash
   sudo -i -u hadoop
   ```

2. Создайте в HDFS тестовую папку `/test`:
   
   ```bash
   hdfs dfs -mkdir /test
   ```

3. Скачайте тестовый файл (пример с сайта Роспатента):
   
   ```bash
   wget --no-check-certificate \
   https://rospatent.gov.ru/opendata/7730176088-tz/data-20241101-structure-20180828.csv
   ```

4. Загрузите его в HDFS:
   
   ```bash
   hdfs dfs -put data-20241101-structure-20180828.csv /test
   ```

5. Убедитесь, что файл появился в **NameNode UI** (по адресу `http://localhost:9870/` при проброшенном порте).

---

## 4. Настройка YARN

Перейдём к настройке YARN. У нас есть заранее подготовленные файлы:
- `yarn-site.xml`
- `mapred-site.xml`

Они должны лежать в директории `hadoop-3.4.0/etc/hadoop/` **на каждой** из нод NameNode и DataNode.

### 4.1. Копируем конфиги на все ноды

> На jump-ноде, где лежат подготовленные файлы, выполним:

```bash
# Копируем yarn-site.xml
scp yarn-site.xml tmpl-nn:/home/hadoop/hadoop-3.4.0/etc/hadoop
scp yarn-site.xml tmpl-dn-00:/home/hadoop/hadoop-3.4.0/etc/hadoop
scp yarn-site.xml tmpl-dn-01:/home/hadoop/hadoop-3.4.0/etc/hadoop

# Копируем mapred-site.xml
scp mapred-site.xml tmpl-nn:/home/hadoop/hadoop-3.4.0/etc/hadoop
scp mapred-site.xml tmpl-dn-00:/home/hadoop/hadoop-3.4.0/etc/hadoop
scp mapred-site.xml tmpl-dn-01:/home/hadoop/hadoop-3.4.0/etc/hadoop
```

### 4.2. Запускаем YARN

1. Подключаемся к **NameNode** (tmpl-nn):
   
   ```bash
   ssh tmpl-nn
   ```
2. Запускаем YARN:
   
   ```bash
   cd ~/hadoop-3.4.0/sbin
   ./start-yarn.sh
   ```
3. Возвращаемся на jump node:
   
   ```bash
   exit
   ```

---

## 5. Дополнительная настройка Nginx (на Jump Node)

Для удобства просмотра интерфейсов (ResourceManager, HistoryServer) пробросим и настроим ещё несколько портов.

1. Скопируем текущий `/etc/nginx/sites-available/default` для бэкапа/других целей:
   
   ```bash
   sudo cp /etc/nginx/sites-available/default /etc/nginx/sites-available/nn
   ```
2. Загрузим два новых файла конфигурации для Nginx:
   - `nginx-ya.conf` в `/etc/nginx/sites-available/ya`
   - `nginx-dh.conf` в `/etc/nginx/sites-available/dh`
   
   (Команды копирования зависят от того, где лежат эти файлы. Примерно так:)
   ```bash
   sudo cp nginx-ya.conf /etc/nginx/sites-available/ya
   sudo cp nginx-dh.conf /etc/nginx/sites-available/dh
   ```
3. Активируем новые конфигурации:
   
   ```bash
   sudo ln -s /etc/nginx/sites-available/ya /etc/nginx/sites-enabled/ya
   sudo ln -s /etc/nginx/sites-available/dh /etc/nginx/sites-enabled/dh
   sudo ln -s /etc/nginx/sites-available/nn /etc/nginx/sites-enabled/nn
   ```
4. Перезапускаем Nginx:
   
   ```bash
   sudo systemctl restart nginx
   ```

---

## 6. Проброс портов для YARN UI

Для работы с **ResourceManager (порт 8088)** и **JobHistoryServer (порт 19888)** пробросим соответствующие порты. Завершаем SSH-сессию и подключаемся заново:

```bash
exit

ssh -L 9870:127.0.0.1:9870 \
    -L 8088:127.0.0.1:8088 \
    -L 19888:127.0.0.1:19888 \
    176.109.91.34
```

Теперь:
- **NameNode UI** доступен по адресу `http://localhost:9870/`
- **ResourceManager UI** доступен по адресу `http://localhost:8088/`
- **JobHistoryServer UI** доступен по адресу `http://localhost:19888/`

---

## 7. Проверка

1. Убедитесь, что **NodeManager** процессы запущены на `tmpl-dn-00` и `tmpl-dn-01`.
2. Перейдите в веб-интерфейс **ResourceManager** по адресу `http://localhost:8088/` (при проброшенном порте) и проверьте, что видны все ноды.
3. Запустите тестовое задание MapReduce для окончательной проверки (например, `pi` или другую утилиту), чтобы убедиться, что всё работает корректно.

---

### Поздравляем!  
YARN успешно настроен и запущен на кластере Hadoop из 4 нод.
