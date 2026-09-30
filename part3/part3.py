#!/usr/bin/env python3

import os
import time

import googleapiclient.discovery
import google.oauth2.service_account as service_account


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT") or "csci-5253-lab2-507421"

# us-west1-b had resource-capacity problems during development,
# so use us-west1-a for the working Part 3 test.
ZONE = "us-west1-a"

VM1_NAME = "lab5-vm1-launcher"
VM2_NAME = "lab5-vm2-flask"

CREDENTIAL_FILE = "service-credentials.json"


# ---------------------------------------------------------
# Authenticate using the explicit service account
# ---------------------------------------------------------

credentials = service_account.Credentials.from_service_account_file(
    filename=CREDENTIAL_FILE
)

service = googleapiclient.discovery.build(
    "compute",
    "v1",
    credentials=credentials
)


# ---------------------------------------------------------
# Wait for a zonal Compute Engine operation
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# Get Ubuntu 22.04 image
# ---------------------------------------------------------

def get_ubuntu_image(compute):
    image_response = compute.images().getFromFamily(
        project="ubuntu-os-cloud",
        family="ubuntu-2204-lts"
    ).execute()

    return image_response["selfLink"]


# ---------------------------------------------------------
# Python program that will execute ON VM-1
#
# VM-1 uses the service-account JSON file to authenticate
# and then creates VM-2.
# ---------------------------------------------------------

VM1_LAUNCH_VM2_CODE = r'''#!/usr/bin/env python3

import os
import time

import googleapiclient.discovery
import google.oauth2.service_account as service_account


PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
ZONE = "us-west1-a"
VM2_NAME = "lab5-vm2-flask"

credentials = service_account.Credentials.from_service_account_file(
    "/srv/service-credentials.json"
)

compute = googleapiclient.discovery.build(
    "compute",
    "v1",
    credentials=credentials
)


def wait_for_operation(compute, project, zone, operation):
    while True:
        result = compute.zoneOperations().get(
            project=project,
            zone=zone,
            operation=operation
        ).execute()

        if result["status"] == "DONE":
            if "error" in result:
                raise Exception(result["error"])

            return result

        time.sleep(1)


# Get Ubuntu 22.04 image
image_response = compute.images().getFromFamily(
    project="ubuntu-os-cloud",
    family="ubuntu-2204-lts"
).execute()

source_disk_image = image_response["selfLink"]


# Read the startup script that VM-2 should execute
with open("/srv/vm2-startup-script.sh", "r") as f:
    vm2_startup_script = f.read()


machine_type = f"zones/{ZONE}/machineTypes/e2-micro"


config = {
    "name": VM2_NAME,

    "machineType": machine_type,

    "metadata": {
        "items": [
            {
                "key": "startup-script",
                "value": vm2_startup_script
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
    ],

    "tags": {
        "items": [
            "allow-5000"
        ]
    }
}


print(f"VM-1 is creating VM-2: {VM2_NAME}")


operation = compute.instances().insert(
    project=PROJECT,
    zone=ZONE,
    body=config
).execute()


wait_for_operation(
    compute,
    PROJECT,
    ZONE,
    operation["name"]
)


instance = compute.instances().get(
    project=PROJECT,
    zone=ZONE,
    instance=VM2_NAME
).execute()


external_ip = (
    instance["networkInterfaces"][0]
    ["accessConfigs"][0]
    ["natIP"]
)


print("VM-2 created successfully.")
print(f"External IP: {external_ip}")
print(f"Flask URL: http://{external_ip}:5000")
'''


# ---------------------------------------------------------
# Startup script for VM-2
#
# This is essentially the Part 1 Flask startup script.
# ---------------------------------------------------------

VM2_STARTUP_SCRIPT = r'''#!/bin/bash

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
'''


# ---------------------------------------------------------
# VM-1 startup script
#
# VM-1 retrieves everything that part3.py placed in metadata.
# It then installs the Google API Python libraries and executes
# the VM-2 creation program.
# ---------------------------------------------------------

VM1_STARTUP_SCRIPT = r'''#!/bin/bash

mkdir -p /srv
cd /srv

curl \
  http://metadata/computeMetadata/v1/instance/attributes/vm2-startup-script \
  -H "Metadata-Flavor: Google" \
  > vm2-startup-script.sh

curl \
  http://metadata/computeMetadata/v1/instance/attributes/service-credentials \
  -H "Metadata-Flavor: Google" \
  > service-credentials.json

curl \
  http://metadata/computeMetadata/v1/instance/attributes/vm1-launch-vm2-code \
  -H "Metadata-Flavor: Google" \
  > vm1-launch-vm2-code.py

export GOOGLE_CLOUD_PROJECT=$(curl \
  http://metadata/computeMetadata/v1/instance/attributes/project \
  -H "Metadata-Flavor: Google")

apt-get update
apt-get install -y python3 python3-pip

pip3 install --upgrade \
  google-api-python-client \
  google-auth \
  google-auth-httplib2

python3 /srv/vm1-launch-vm2-code.py \
  > /var/log/vm1-launch-vm2.log 2>&1
'''


# ---------------------------------------------------------
# Create VM-1
# ---------------------------------------------------------

def create_vm1(compute, project, zone, name):
    source_disk_image = get_ubuntu_image(compute)

    machine_type = f"zones/{zone}/machineTypes/e2-micro"

    # Read the service-account credential JSON as a string.
    #
    # Do NOT print this value.
    with open(CREDENTIAL_FILE, "r") as credential_file:
        credential_contents = credential_file.read()

    config = {
        "name": name,

        "machineType": machine_type,

        "metadata": {
            "items": [
                {
                    "key": "startup-script",
                    "value": VM1_STARTUP_SCRIPT
                },
                {
                    "key": "vm2-startup-script",
                    "value": VM2_STARTUP_SCRIPT
                },
                {
                    "key": "service-credentials",
                    "value": credential_contents
                },
                {
                    "key": "vm1-launch-vm2-code",
                    "value": VM1_LAUNCH_VM2_CODE
                },
                {
                    "key": "project",
                    "value": project
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

    print(f"Creating VM-1 '{name}'...")

    return compute.instances().insert(
        project=project,
        zone=zone,
        body=config
    ).execute()


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

if __name__ == "__main__":

    print(f"Project: {PROJECT}")
    print(f"Zone: {ZONE}")
    print()

    operation = create_vm1(
        service,
        PROJECT,
        ZONE,
        VM1_NAME
    )

    wait_for_operation(
        service,
        PROJECT,
        ZONE,
        operation["name"]
    )

    print()
    print("VM-1 has been created.")
    print()
    print("VM-1's startup script will now:")
    print("  1. Retrieve the service credentials from metadata")
    print("  2. Retrieve the VM-2 startup script")
    print("  3. Retrieve the VM-2 Python launcher")
    print("  4. Install the Google API libraries")
    print("  5. Authenticate using the service account")
    print("  6. Create VM-2")
    print()
    print("VM-2 creation happens asynchronously inside VM-1.")