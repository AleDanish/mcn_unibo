#!/bin/bash
Tstart=$(date +%s%3N) 

#compress and send with one command
#ssh -i /home/ubuntu/key/mcn-key.pem ubuntu@ip_old 'cd /var/lib/influxdb; sudo tar zcvf - data hh wal meta' > influxdb.backup.tar.gz

if [ "$1" == "" ]; then
   oldfloatingip=$(<../influxdb_oldip)
else oldfloatingip=$1
fi
echo $oldfloatingip

#compress data
#Tcompress_start=$(date +%s%3N)
#ssh -oStrictHostKeyChecking=no -i /home/ubuntu/key/mcn-key.pem ubuntu@$oldfloatingip 'cd /var/lib/influxdb; sudo tar -cf /home/ubuntu/influxdb.backup.tar meta data hh wal'
#Tcompress_end=$(date +%s%3N)

sudo rm /home/ubuntu/influxdb.backup.tar.gz
#send data
Tmove_start=$(date +%s%3N)
#scp -oStrictHostKeyChecking=no -i /home/ubuntu/key/mcn-key.pem ubuntu@$oldfloatingip:/home/ubuntu/influxdb.backup.tar /home/ubuntu/
ssh -oStrictHostKeyChecking=no -i /home/ubuntu/key/mcn-key.pem ubuntu@$oldfloatingip 'cd /var/lib/influxdb; sudo tar zcf - data hh wal meta' > /home/ubuntu/influxdb.backup.tar.gz

Tmove_end=$(date +%s%3N)
#remove data folders
echo "cancello i dati"
sudo rm -rf /var/lib/influxdb/*
#extract data
Textract_start=$(date +%s%3N)
echo "estraggo i dati"
sudo tar -xf /home/ubuntu/influxdb.backup.tar -C /var/lib/influxdb
Textract_end=$(date +%s%3N)
#restart database
Trestart_start=$(date +%s%3N)
echo "database restart"
sudo service influxdb restart
Trestart_end=$(date +%s%3N)
Tend=$(date +%s%3N)

Tcompress=$(((Tcompress_end-Tcompress_start)/1000))
Tmove=$(((Tmove_end-Tmove_start)/1000))
Textract=$(((Textract_end-Textract_start)/1000))
Trestart=$(((Trestart_end-Trestart_start)/1000))
Ttotal=$(((Tend-Tstart)/1000))

sudo rm /home/ubuntu/times_influxdb
#sudo echo "Time to compress data: " $Tcompress >> /home/ubuntu/times_influxdb
sudo echo "Time to move data: " $Tmove >> /home/ubuntu/times_influxdb
sudo echo "Time to extract data: " $Textract >> /home/ubuntu/times_influxdb
sudo echo "Time to restart data: " $Trestart >> /home/ubuntu/times_influxdb
sudo echo "Time total: " $Ttotal >> /home/ubuntu/times_influxdb
