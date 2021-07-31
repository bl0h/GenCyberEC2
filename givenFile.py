import boto3, logging, json
import datetime, time
import random

logger = logging.getLogger()
logger.setLevel(logging.INFO)
TESTING = False
# EC2 instance are automatically TERMINATED at the ChallengeEndTime, unless TESTING = True


# Setup EC2, S3, and DynamoDB resources
EC2c = boto3.client("ec2")
EC2r = boto3.resource("ec2")
S3 = boto3.client('s3')
dynamodb = boto3.resource("dynamodb")


# ********* The master AMIs have a default password for all *********
# ** Default AMI selected is DIFFICULT **
AMI_INTERMEDIATE = "ami-0ff161271b362a3e0"
AMI_DIFFICULT = "ami-06578d5d734e15898"

# Specify EC2 instance and volume size
INSTANCE_SIZE = "m5a.xlarge"
VOLUME_SIZE = 65 #in GB

# VPC and Security Group IDs
VPC = "vpc-0630ccf0da32f86f3"
SG = "sg-08364137bb7a1306c"

# DynamoDB table name for challenge details
DB_DETAILS = "ccic2020-indiv-ChallengeDetails"
DB_USERS = "ccic2020-indiv-Users"


def lambda_handler(event, context):
    logger.info('event info: {}'.format(event))
    
    
    # Appropriate headers for CORS specifications
    response = {
        "isBase64Encoded": "false",
        "statusCode": 200,
        "headers": {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, PUT, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Date,X-Amzn-Trace-Id,x-amz-apigw-id,x-amzn-RequestId,Authorization"
        }
    }
    result = {}
    
    
    # Work-around for state machine to execute termination of instance (fully-managed server-side)
    instance = event.get("sm-instanceId")
    userEmail = event.get("sm-userEmail")
    if instance != None and userEmail != None:
        terminateInstance(instance)
        return response

    
    # Obtain email from Cognito credentials
    try:
        email = event['requestContext']['authorizer']['claims']['email']
        email = email.lower()
        user = email.split('@')[0]
        print(email)
    except KeyError:
        return requestError(response, 400, "Missing user Cognito credentials/invalid email in request payload.")
    

    # Obtain competition and user details
    try:
        challengeDetails = dynamodb.Table(DB_DETAILS)
        start = challengeDetails.get_item(Key={'Name': 'ChallengeStartUTC'})['Item']['Value']
        end = challengeDetails.get_item(Key={'Name': 'ChallengeEndUTC'})['Item']['Value']
        pwd = challengeDetails.get_item(Key={'Name': 'serverPassword'})['Item']['Value']
        
        userInfo = dynamodb.Table(DB_USERS)
        
    except:
        return requestError(response, 400, "Issue with obtaining details from DynamoDB tables.")
    
    
    # Validate challenge time frame (or always allow if testing)
    if not TESTING and not checkValidTime(start, end):
        return requestError(response, 400, "The competition is OVER")

    
    # Obtain list of EC2 instances
    totalInstances = describeInstances(user)
    liveInstances = describeInstances(user, live = True)
    logger.info("total instances: {}".format(totalInstances))
    logger.info("live instances: {}".format(liveInstances))
    
    
    # Ensures that user only has 1 live instance
    if len(liveInstances) > 1:
        return requestError(response, 400, "There exists more than 1 (live) instance for this user.")
        
        
    # Which path did we get from API Gateway indicating the method to execute?
    try:
        action = event['pathParameters']['proxy'].lower()
        logger.info("action: {}".format(action))
    except KeyError:
        logger.error("Missing action in event")
        return requestError(response, 400, "No action has been identified")
    
    
    # Init - initalize EC2 instance for user
    if action == "init":
        # Create EC2 instance as long as user does not already have a live one
        if len(totalInstances) > 0:
            id = [instance.id for instance in totalInstances]
            return requestError(response, 400, id[0] + " - User cannot initialize more than 1 instance.")
            
        elif not TESTING and checkValidTime(start, end) == False:
            return requestError(resopnse, 400, "User can no longer create an instance.")
        instance = createInstance(user)

        # Get challenge end time from table
        endTime = datetime.datetime.fromisoformat(end)
        currentTime = datetime.datetime.utcnow()

        # Prepare EC2 instance details to be presented to user
        instanceDetails = {
            "instanceId": instance.instance_id,
            "launchTime": str(instance.launch_time),
            "publicIpAddress": instance.public_ip_address,
            "state": instance.state,
            "stateReason": instance.state_reason
        }
        
        # Set timer to terminate EC2 instance at the pre-determined challenge end time
        calcTimeLimit = endTime - currentTime
        waitPeriod = int(calcTimeLimit.total_seconds()) if not TESTING else 60 * 60
        setTimer(email, instanceDetails['instanceId'], waitPeriod)
        result = instanceDetails
    
    
    # Reboot - reboot EC2 instance for user
    elif action == "reboot":
        # Ensure there is a live instance to reboot before doing so
        try:
            if len(liveInstances) < 1:
                return requestError(response, 400, "No live instance to reboot.")
            instances = [instance.id for instance in liveInstances]
            rebootInstance(instances)
            result = instances
            
        except Exception as e:
            logger.error(str(e))
            return requestError(response, 500, "Instance could not be rebooted.")
    
    
    # Stop - stop EC2 instance for user
    elif action == "stop":
        # Ensure there is a live instance to stop before doing so
        try:
            if len(liveInstances) < 1:
                return requestError(response, 400, "No live instance to stop.")
            instances = [instance.id for instance in liveInstances]
            result = stopInstance(instances)
            
        except Exception as e:
            logger.error(str(e))
            return requestError(response, 500, "Instance could not be stopped.")
    
    
    # Password - display instance's pre-defined password
    elif action == "password":
        # Ensure there is a live instance with a password before doing so
        try:
            if len(liveInstances) < 1:
                return requestError(response, 400, "No live instances(s) to report password.")
            result = {"password": pwd}
            
        except Exception as e:
            logger.error(str(e))
            return requestError(response, 500, "Password for instance could not be reported.")
    
    
    # IP - obtain IP address of EC2 instance for user
    elif action == "ip":
        # Ensure there is a live instance with an IP before doing so
        try:
            if len(liveInstances) < 1:
                return requestError(response, 400, "No instance to report public IP.")
            result = getPublicIP(liveInstances[0])
            
        except Exception as e:
            logger.error(str(e))
            return requestError(response, 500, "IP for instance could not be reported.")
    
    
    # State - obtain state of EC2 instance for user
    elif action == "state":
        # Ensure there is a live instance to reboot before doing so
        try:
            if len(totalInstances) < 1:
                return requestError(response, 400, "No instance to report status.")
            result = {
                "state": getState(totalInstances[0]),
                "status": getStatus(totalInstances[0])
            }
            
        except Exception as e:
            logger.error(str(e))
            return requestError(response, 500, "State for instance could not be reported.")


    # Invalid request by user
    else:
        return requestError(response, 404, "Unknown action requested")
    
    
    # Respond to request
    response['body'] = json.dumps(result)
    return response



# Returns if current time is within the valid competition time frame
def checkValidTime(start, end):
    startTime = datetime.datetime.fromisoformat(start)
    endTime = datetime.datetime.fromisoformat(end)
    currentTime = datetime.datetime.utcnow()
    return startTime <= currentTime <= endTime



# Returns the subnet id from a set of subnets based on a uniformly distributed random variable
def setSubnet():
    vpc = EC2r.Vpc(VPC)
    subnets = [subnet for subnet in vpc.subnets.all()]
    count = len(subnets)
    subnet = subnets[random.randrange(count)]
    return subnet.id
    


# Returns an array of EC2 instance objects
def describeInstances(user, live = None):
    userFilter = {
        "Name": "tag:Name",
        "Values": [user]
    }
    
    # Intend to only find live, terminated, or stopped EC2 instances
    if live != None:
        states = ["running",  "pending", "shutting-down"] if live else ["stopping", "stopped", "terminated"]
        instanceState = {
            "Name": "instance-state-name",
            "Values": states
        }
        return [instance for instance in EC2r.instances.filter(Filters=[userFilter, instanceState])]
        
    return [instance for instance in EC2r.instances.filter(Filters=[userFilter])]



# Reboots the specified EC2 instance
def rebootInstance(instanceList):
    response = EC2c.reboot_instances(InstanceIds=instanceList)
    return response



# Stops the specified EC2 instance
def stopInstance(instanceList):
    response = EC2c.stop_instances(InstanceIds=instanceList)
    return response



# Returns the specified EC2 instance's PUBLIC IP address
def getPublicIP(instance):
    return {"ipAddress": instance.public_ip_address}



# Returns the specified EC2 instance's state
def getState(instance):
   return instance.state



# Returns the specified EC2 instance's state
def getStatus(instance):
    status = "n/a"
    if(instance.state["Name"] == "running"):
        statusInfo = EC2c.describe_instance_status(InstanceIds=[instance.instance_id])
        status = statusInfo["InstanceStatuses"][0]["InstanceStatus"]["Status"]
    return status



# Returns a newly created EC2 instance
def createInstance(user):
    # Choose EC2 AMI (default = DIFFICULT)
    instanceAMI = AMI_DIFFICULT
    
    newInstance = EC2r.create_instances(
        ImageId=instanceAMI,
        MinCount=1,
        MaxCount=1,
        InstanceType=INSTANCE_SIZE,
        SubnetId=setSubnet(),
        SecurityGroupIds=[SG],
        TagSpecifications=[
            {
                'ResourceType': 'instance',
                'Tags': [{
                    'Key': 'Name',
                    'Value': user
                }]
            }
        ],
        BlockDeviceMappings=[
            {
                'DeviceName': '/dev/sda1',
                'Ebs': {
                    'VolumeSize': VOLUME_SIZE,
                    'VolumeType': 'gp2'
                }
            }
        ]
    )
    logger.info("Instance created for {0}: {1}".format(user, newInstance[0]))
    return newInstance[0]



# Error response
def requestError(response, status_code, body):
    response['statusCode'] = str(status_code)
    error = { "error": body }
    logger.error(body)
    response['body'] = json.dumps(error)
    return response



# ---------------------------STEP FUNCTION METHODS------------------------------



# Sets the timer for the specified EC2 instance to terminate
def setTimer(email, instanceId, waitPeriod):
    user = email.split('@')[0]
    client = boto3.client('stepfunctions')
    
    body = '{"sm-instanceId": "' + instanceId + '", "waitPeriod": "' + str(waitPeriod) + '", "sm-userEmail": "' + email + '"}'
    response = client.start_execution(
        stateMachineArn="arn:aws:states:us-west-2:752841263249:stateMachine:EC2TerminationTimer",
        name=user + "_" + str(datetime.datetime.utcnow()).replace(" ", "_").replace(":", "-"),
        input=str(body))



# Terminates the specified EC2 instance
def terminateInstance(instanceId):
    # Check that the state is not terminated before executing the following command
    EC2c.terminate_instances(InstanceIds=[instanceId])
    
    
    
# -------------------------END STEP FUNCTION METHODS----------------------------