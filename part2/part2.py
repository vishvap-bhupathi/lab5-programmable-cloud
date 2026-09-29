#!/usr/bin/env python3

import time

import googleapiclient.discovery
import google.auth


# Authenticate using Application Default Credentials
credentials, project = google.auth.default()

# Create Compute Engine API client
service = googleapiclient.discovery.build(
    "compute",
    "v1",
    credentials=credentials
)


def wait_for_zone_operation(compute, project, zone, operation):
    """
    Wait for a zonal Compute Engine operation to finish.
    """
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


def get_instance_disk(compute, project, zone, instance_name):
    """
    Find the boot disk attached to an instance.
    """
    instance = compute.instances().get(
        project=project,
        zone=zone,
        instance=instance_name
    ).execute()

    disk_url = instance["disks"][0]["source"]

    # Disk name is the last part of the URL.
    disk_name = disk_url.split("/")[-1]

    return disk_name


def create_snapshot(compute, project, zone, instance_name):
    """
    Create base-snapshot-<instance> from the Part 1 VM's disk.
    """
    disk_name = get_instance_disk(
        compute,
        project,
        zone,
        instance_name
    )

    snapshot_name = f"base-snapshot-{instance_name}"

    snapshot_body = {
        "name": snapshot_name
    }

    print(
        f"Creating snapshot '{snapshot_name}' "
        f"from disk '{disk_name}'..."
    )

    operation = compute.disks().createSnapshot(
        project=project,
        zone=zone,
        disk=disk_name,
        body=snapshot_body
    ).execute()

    return operation, snapshot_name


def create_instance_from_snapshot(
    compute,
    project,
    zone,
    instance_name,
    snapshot_name
):
    """
    Create a VM whose boot disk is initialized from our snapshot.
    """

    machine_type = f"zones/{zone}/machineTypes/e2-micro"

    snapshot_url = (
        f"projects/{project}/global/snapshots/{snapshot_name}"
    )

    config = {
        "name": instance_name,

        "machineType": machine_type,

        "disks": [
            {
                "boot": True,
                "autoDelete": True,
                "initializeParams": {
                    "sourceSnapshot": snapshot_url
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

        # The existing allow-5000 firewall rule targets this tag.
        "tags": {
            "items": [
                "allow-5000"
            ]
        }
    }

    print(f"Creating instance '{instance_name}'...")

    operation = compute.instances().insert(
        project=project,
        zone=zone,
        body=config
    ).execute()

    return operation


def get_external_ip(compute, project, zone, instance_name):
    """
    Retrieve the external IP address of an instance.
    """
    instance = compute.instances().get(
        project=project,
        zone=zone,
        instance=instance_name
    ).execute()

    return instance["networkInterfaces"][0]["accessConfigs"][0]["natIP"]


if __name__ == "__main__":

    # -------------------------------------------------------
    # Source VM from Part 1
    #
    # Our successfully created Part 1 VM is currently in
    # us-west1-a because us-west1-b had insufficient capacity.
    # -------------------------------------------------------

    source_zone = "us-west1-a"
    source_instance = "lab5-part1-python"

    # Use the same zone for the three cloned VMs.
    clone_zone = "us-west1-a"

    print(f"Project: {project}")
    print(f"Source instance: {source_instance}")
    print(f"Source zone: {source_zone}")
    print()

    # -------------------------------------------------------
    # 1. Find the Part 1 VM's disk
    # -------------------------------------------------------

    disk_name = get_instance_disk(
        service,
        project,
        source_zone,
        source_instance
    )

    print(f"Source disk: {disk_name}")
    print()

    # -------------------------------------------------------
    # 2. Create the snapshot
    # -------------------------------------------------------

    snapshot_operation, snapshot_name = create_snapshot(
        service,
        project,
        source_zone,
        source_instance
    )

    wait_for_zone_operation(
        service,
        project,
        source_zone,
        snapshot_operation["name"]
    )

    print()
    print(f"Snapshot '{snapshot_name}' created successfully.")
    print()

    # -------------------------------------------------------
    # 3. Create three VMs from the snapshot and time each one
    # -------------------------------------------------------

    timings = []

    for i in range(1, 4):

        instance_name = f"lab5-clone-{i}"

        print("----------------------------------------")
        print(f"Creating clone {i}: {instance_name}")

        start_time = time.perf_counter()

        operation = create_instance_from_snapshot(
            service,
            project,
            clone_zone,
            instance_name,
            snapshot_name
        )

        wait_for_zone_operation(
            service,
            project,
            clone_zone,
            operation["name"]
        )

        end_time = time.perf_counter()

        elapsed_time = end_time - start_time

        timings.append(
            (instance_name, elapsed_time)
        )

        external_ip = get_external_ip(
            service,
            project,
            clone_zone,
            instance_name
        )

        print(
            f"{instance_name} created in "
            f"{elapsed_time:.2f} seconds."
        )

        print(
            f"External IP: {external_ip}"
        )

        print()

    # -------------------------------------------------------
    # 4. Display timing results
    # -------------------------------------------------------

    print()
    print("========================================")
    print("INSTANCE CREATION TIMES")
    print("========================================")

    for instance_name, elapsed_time in timings:
        print(
            f"{instance_name}: "
            f"{elapsed_time:.2f} seconds"
        )