#!/usr/bin/env python3

import argparse
import os
import time
from pprint import pprint

import googleapiclient.discovery
import google.auth

import urllib.request
import urllib.error

credentials, project = google.auth.default()
service = googleapiclient.discovery.build('compute', 'v1', credentials=credentials)

#
# Stub code - just lists all instances
#
def list_instances(compute, project, zone):
    result = compute.instances().list(project=project, zone=zone).execute()
    return result.get("items", [])

def create_instance(compute, project, zone, name):
    # Get the latest Ubuntu 22.04 image
    image_response = compute.images().getFromFamily(
        project="ubuntu-os-cloud",
        family="ubuntu-2204-lts"
    ).execute()

    source_disk_image = image_response["selfLink"]

    machine_type = f"zones/{zone}/machineTypes/f1-micro"
    startup_script = """#!/bin/bash

    apt-get update
    apt-get install -y python3 python3-pip git
    
    cd /opt
    
    git clone https://github.com/cu-csci-4253-datacenter/flask-tutorial
    cd flask-tutorial
    
    python3 setup.py install
    pip3 install -e .
    
    export FLASK_APP=flaskr
    flask init-db
    
    nohup flask run -h 0.0.0.0 > /var/log/flask.log 2>&1 &
    """
    config = {
        "name": name,

        "machineType": machine_type,

        "metadata": {
            "items": [
                {
                    "key": "startup-script",
                    "value": startup_script
                }
            ]
        },

        "disks": [
            {
                "boot": True,
                "autoDelete": True,
                "initializeParams": {
                    "sourceImage": source_disk_image
                }
            }
        ],

        "networkInterfaces": [
            {
                "network": "global/networks/default",
                "accessConfigs": [
                    {
                        "type": "ONE_TO_ONE_NAT",
                        "name": "External NAT"
                    }
                ]
            }
        ]
    }

    return compute.instances().insert(
        project=project,
        zone=zone,
        body=config
    ).execute()

def wait_for_operation(compute, project, zone, operation):
    print(f"Waiting for operation {operation} to finish...")

    while True:
        result = compute.zoneOperations().get(
            project=project,
            zone=zone,
            operation=operation
        ).execute()

        if result["status"] == "DONE":
            if "error" in result:
                raise Exception(result["error"])

            print("Operation finished.")
            return result

        time.sleep(1)

def ensure_firewall_rule(compute, project):
    firewall_name = "allow-5000"

    # Check whether the firewall rule already exists
    result = compute.firewalls().list(project=project).execute()

    for firewall in result.get("items", []):
        if firewall["name"] == firewall_name:
            print(f"Firewall rule '{firewall_name}' already exists.")
            return

    # Rule does not exist, so create it
    firewall_body = {
        "name": firewall_name,
        "network": f"projects/{project}/global/networks/default",
        "allowed": [
            {
                "IPProtocol": "tcp",
                "ports": ["5000"]
            }
        ],
        "sourceRanges": ["0.0.0.0/0"],
        "targetTags": ["allow-5000"]
    }

    print(f"Creating firewall rule '{firewall_name}'...")

    operation = compute.firewalls().insert(
        project=project,
        body=firewall_body
    ).execute()

    return operation

def wait_for_global_operation(compute, project, operation):
    print(f"Waiting for operation {operation} to finish...")

    while True:
        result = compute.globalOperations().get(
            project=project,
            operation=operation
        ).execute()

        if result["status"] == "DONE":
            if "error" in result:
                raise Exception(result["error"])

            print("Operation finished.")
            return result

        time.sleep(1)

def set_instance_tags(compute, project, zone, instance_name):
    # Get the current instance so we can retrieve its tag fingerprint
    instance = compute.instances().get(
        project=project,
        zone=zone,
        instance=instance_name
    ).execute()

    fingerprint = instance["tags"]["fingerprint"]

    tags_body = {
        "items": ["allow-5000"],
        "fingerprint": fingerprint
    }

    print(f"Adding 'allow-5000' tag to {instance_name}...")

    operation = compute.instances().setTags(
        project=project,
        zone=zone,
        instance=instance_name,
        body=tags_body
    ).execute()

    return operation

def wait_for_flask(external_ip, timeout=600):
    url = f"http://{external_ip}:5000"
    print("Waiting for Flask application to start...")

    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    print("Flask application is ready.")
                    return
        except (urllib.error.URLError, TimeoutError):
            pass

        time.sleep(10)

    print("Warning: Flask did not become ready within the timeout.")

def get_external_ip(compute, project, zone, instance_name):
    instance = compute.instances().get(
        project=project,
        zone=zone,
        instance=instance_name
    ).execute()

    return instance["networkInterfaces"][0]["accessConfigs"][0]["natIP"]

if __name__ == "__main__":
    zone = "us-west1-b"
    instance_name = "lab5-part1-python"

    print(f"Project: {project}")
    print(f"Creating instance '{instance_name}' in {zone}...")

    operation = create_instance(
        service,
        project,
        zone,
        instance_name
    )

    wait_for_operation(
        service,
        project,
        zone,
        operation["name"]
    )

    # Make sure the firewall rule exists
    firewall_operation = ensure_firewall_rule(service, project)

    if firewall_operation:
        wait_for_global_operation(
            service,
            project,
            firewall_operation["name"]
        )

    # Apply the network tag
    tag_operation = set_instance_tags(
        service,
        project,
        zone,
        instance_name
    )

    wait_for_operation(
        service,
        project,
        zone,
        tag_operation["name"]
    )

    # Retrieve the VM's external IP
    external_ip = get_external_ip(
        service,
        project,
        zone,
        instance_name
    )

    wait_for_flask(external_ip)

    print()
    print("The Flask application is available at:")
    print(f"http://{external_ip}:5000")