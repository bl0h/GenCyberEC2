import boto3


def startInstances(instances):
    ec2 = boto3.resource('ec2')

    newInstance = ec2.create_instances(
        ImageId= 'ami-0c89cba549f290d34',
        MinCount= instances,
        MaxCount= instances,
        InstanceType= 't3.medium',
        KeyName = 'GenCyber 2021',
        SecurityGroupIds=['sg-0bf47b7e8e984bb9b'],
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [{
                    'Key': 'Name',
                    'Value': 'GenCyber Wireshark/Autopsy'
                }]
            }
        ]
    )

if __name__ == "__main__":
    numInstances = input('Start how many instances? ')
    if int(numInstances) > 100:
        numInstances = '1'
    startInstances(int(numInstances))
    print(str(numInstances), 'instance(s) started')