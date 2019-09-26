#!/bin/bash
sudo ip link set can0 type can bitrate 125000
sudo ip link set up dev can0
sudo ip link set can1 type can bitrate 125000
sudo ip link set up dev can1
