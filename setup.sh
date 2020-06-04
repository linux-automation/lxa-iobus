#!/bin/bash
sudo ip link set can0 type can bitrate 100000
sudo ip link set up dev can0
