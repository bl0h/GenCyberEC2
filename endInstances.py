import boto3

def endInstances():
    ec2 = boto3.resource('ec2')
    counter = 0
    instances = ec2.instances.filter(
        Filters=[{'Name': 'instance-state-name', 'Values': ['running']},
                 {'Name': 'tag:Name', 'Values': ['GenCyber Wireshark/Autopsy']} ])
    for instance in instances:
        counter += 1
        ec2.instances.filter(InstanceIds=[instance.id]).terminate()
    return counter

if __name__ == "__main__":
    num = endInstances()
    print(str(num), 'instance(s) terminated')