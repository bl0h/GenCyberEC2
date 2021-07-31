import boto3


def getID():
    ec2 = boto3.resource('ec2')
    idList = []
    instances = ec2.instances.filter(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']},
                 {'Name': 'tag:Name', 'Values': ['GenCyber Wireshark/Autopsy']} ])
    for instance in instances:
        idList.append(instance.id)
    return idList

def get_public_ip(instance_id):
    ec2_client = boto3.client("ec2", region_name="us-west-2")
    reservations = ec2_client.describe_instances(InstanceIds=[instance_id]).get("Reservations")
    for reservation in reservations:
        for instance in reservation['Instances']:
            return instance.get("PublicIpAddress")

if __name__ == "__main__":
    idList = getID()
    outfile = open('ipList.txt', 'w')
    for id in idList:
        ip = get_public_ip(id)
        outfile.write(ip + '\n')
    print(str(len(idList)) + " ip(s) copied down to file")