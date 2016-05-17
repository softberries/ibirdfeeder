#!/usr/bin/python

import paho.mqtt.client as paho
import os
import ssl
import sys
import picamera
import RPi.GPIO as GPIO
import time
import logging
from PIL import Image

from time import sleep
from boto.s3.connection import S3Connection
from boto.s3.key import Key
from w1thermsensor import W1ThermSensor

## Local imports
from ConfigMap import configSectionMap

## Basic setup
conn = S3Connection(configSectionMap("AWS")['aws_access'], configSectionMap("AWS")['aws_secret'])
bucket = conn.get_bucket(configSectionMap("AWS")['bucket_name'])

camera = picamera.PiCamera()
camera.rotation = 180
mqttc = paho.Client()
sensor = W1ThermSensor()

## Logger Settings
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.FileHandler(configSectionMap("LOGGING")['log_file'])
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

COMMAND_TOPIC = configSectionMap("IOT")['command_topic']
TEMPERATURE_TOPIC = configSectionMap("IOT")['temperature_topic']
IMAGE_CREATED_TOPIC = configSectionMap("IOT")['image_created_topic']
VIDEO_CREATED_TOPIC = configSectionMap("IOT")['video_created_topic']
TAKE_PHOTO_CMD = configSectionMap("IOT")['take_photo_cmd']
RECORD_VIDEO_CMD = configSectionMap("IOT")['record_video_cmd']
FEED_CMD = configSectionMap("IOT")['feed_cmd']
TEMBERATURE_CMD = configSectionMap("IOT")['temperature_cmd']
TEMPERATURE_STATUS = configSectionMap("IOT")['temperature_status']
RESOURCE_CRATED_STATUS = configSectionMap("IOT")['resource_created_status']

awshost = configSectionMap("IOT")['aws_host']
awsport = int(configSectionMap("IOT")['aws_port'])
clientId = configSectionMap("IOT")['client_id']
thingName = configSectionMap("IOT")['thing_name']
caPath = configSectionMap("IOT")['ca_path']
certPath = configSectionMap("IOT")['cert_path']
keyPath = configSectionMap("IOT")['key_path']

## GPIO Settings
pirPin = int(configSectionMap("GPIO")['pir_pin'])
feederPin = int(configSectionMap("GPIO")['feeder_pin'])
GPIO.setmode(GPIO.BCM)
GPIO.setup(pirPin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(feederPin, GPIO.OUT)
GPIO.output(feederPin, 0)

## Image Settings
smallImgPrefix = configSectionMap("IMAGE")['small_image_prefix']
mediumImgPrefix = configSectionMap("IMAGE")['medium_image_prefix']
smallImgSize = int(configSectionMap("IMAGE")['small_image_width'])
mediumImgSize = int(configSectionMap("IMAGE")['medium_image_width'])

## AWS IoT Settings
connflag = False

## UTIL Functions
def percent_cb(complete, total):
    sys.stdout.write('.')
    sys.stdout.flush()

def upload_S3(dir, file):
    k = Key(bucket)
    k.key = file
    k.set_contents_from_filename(dir + file, cb=percent_cb, num_cb=10)
    logger.info("file " + file + " uploaded.")

def removeLocal(dir, file):
    os.remove(dir + file)
    logger.info("file " + file + " removed from local filesystem.")

## CALLBACK Functions
def on_connect(client, userdata, flags, rc):
    global connflag
    connflag = True
    logger.info("Connection returned result: " + str(rc) )
    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    client.subscribe("#" , 1 )

def on_message(client, userdata, msg):
    logger.info("topic: "+msg.topic)
    logger.info("payload: " + "".join(map(chr, msg.payload)))
    if msg.topic == COMMAND_TOPIC:
        executeCommand("".join(map(chr, msg.payload)))

def executeCommand(command):
    logger.info("received command: " + command)
    if command == TAKE_PHOTO_CMD:
        takePhoto()
    elif command == TEMBERATURE_CMD:
        sendTemperatureReading()
    elif command == RECORD_VIDEO_CMD:
        recordVideo()
    elif command == FEED_CMD:
        runFeeder(5)
    else:
        logger.info("received unknown command " + command)

def sendStatus(topic, status, value):
    mqttc.publish(topic, "{\"" + status + "\":\"" + value + "\"}", qos=1)

def takePhoto():
    logger.info("taking photo...")
    timestr = time.strftime("%Y%m%d-%H%M%S")
    directory = '/home/pi/Pictures/'
    img = 'image_' + timestr + '.jpg'
    camera.resolution = (2592, 1944)
    camera.capture(directory + img)
    logger.info("creating additional image sizes...")
    resize(directory, img, smallImgPrefix, smallImgSize)
    resize(directory, img, mediumImgPrefix, mediumImgSize)
    logger.info("uploading picture to s3 service")
    upload_S3(directory, img)
    upload_S3(directory, smallImgPrefix+img)
    upload_S3(directory, mediumImgPrefix+img)
    removeLocal(directory, img)
    removeLocal(directory, smallImgPrefix+img)
    removeLocal(directory, mediumImgPrefix+img)
    sendStatus(IMAGE_CREATED_TOPIC, RESOURCE_CRATED_STATUS, img)

def recordVideo():
    logger.info("recording video...")
    timestr = time.strftime("%Y%m%d-%H%M%S")
    directory = '/home/pi/Videos/'
    vid = 'video_' + timestr + '.h264'
    camera.resolution = (1920, 1080)
    camera.rotation = 180
    camera.start_recording(directory + vid)
    camera.wait_recording(10)
    camera.stop_recording()
    logger.info("uploading video to s3 service")
    upload_S3(directory, vid)
    logger.info("file " + vid + " uploaded.")
    removeLocal(directory, vid)
    logger.info("file " + vid + " removed from local filesystem.")
    sendStatus(VIDEO_CREATED_TOPIC, RESOURCE_CRATED_STATUS, vid)

def pirCallback(channel):
    logger.info("rising edge detected on 20")
    takePhoto()

def runFeeder(timeToRun):
    logger.info("running feeder pipe")
    GPIO.output(feederPin, 1)
    sleep(timeToRun)
    GPIO.output(feederPin, 0)

def sendTemperatureReading():
    temperature_in_celsius = sensor.get_temperature()
    sendStatus(TEMPERATURE_TOPIC, TEMPERATURE_STATUS, str(temperature_in_celsius))
    logger.info("msg sent: temperature " + "%.2f" % temperature_in_celsius )

def resize(directory, imgFile, prefix, imgSize):
    inFile = Image.open(directory + imgFile)
    outFile = prefix+imgFile
    xDim = inFile.size[0]
    yDim = inFile.size[1]
    newSize = aspectRatio(xDim, yDim, imgSize)
    inFile = inFile.resize((int(newSize[0]),int(newSize[1])),Image.ANTIALIAS)
    inFile.save(directory + outFile)

def aspectRatio(xDim, yDim, imgSize):
    if xDim <= imgSize and yDim <= imgSize: #ensures images already correct size are not enlarged.
        return(xDim, yDim)
    elif xDim > yDim:
        divider = xDim/float(imgSize)
        xDim = float(xDim/divider)
        yDim = float(yDim/divider)
        return(xDim, yDim)
    elif yDim > xDim:
        divider = yDim/float(imgSize)
        xDim = float(xDim/divider)
        yDim = float(yDim/divider)
        return(xDim, yDim)
    elif xDim == yDim:
        xDim = imgSize
        yDim = imgSize
        return(xDim, yDim)

## SETUP
mqttc.on_connect = on_connect
mqttc.on_message = on_message
mqttc.tls_set(caPath, certfile=certPath, keyfile=keyPath, cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLSv1_2, ciphers=None)
mqttc.connect(awshost, awsport, keepalive=60)
mqttc.loop_start()

GPIO.add_event_detect(pirPin, GPIO.RISING, callback=pirCallback, bouncetime=300)

###
### Main loop
###
while 1==1:
    sleep(3)
    if connflag == True:
        sendTemperatureReading()
        sleep(600)
    else:
        logger.info("waiting for connection...")
