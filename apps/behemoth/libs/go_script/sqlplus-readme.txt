下载地址: https://www.oracle.com/database/technologies/instant-client/linux-x86-64-downloads.html
1、instantclient-basic-linux.x64-19.24.0.0.0dbru.zip
2、instantclient-sqlplus-linux.x64-19.24.0.0.0dbru.zip

sh -c "echo /opt/oracle/instantclient_19_24 > /etc/ld.so.conf.d/oracle-instantclient.conf"
ldconfig

export PATH=/opt/oracle/instantclient_19_24:$PATH

