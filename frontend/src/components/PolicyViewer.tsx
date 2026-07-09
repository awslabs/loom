import type { PolicyDocument } from "@/api/types";

const ACTION_DESCRIPTIONS: Record<string, string> = {
  // S3
  "s3:*": "Full access to all Amazon S3 operations",
  "s3:GetObject": "Read an object from an S3 bucket",
  "s3:PutObject": "Write an object to an S3 bucket",
  "s3:DeleteObject": "Delete an object from an S3 bucket",
  "s3:ListBucket": "List objects in an S3 bucket",
  "s3:GetBucketLocation": "Get the region of an S3 bucket",
  "s3:ListAllMyBuckets": "List all S3 buckets in the account",
  "s3:CreateBucket": "Create a new S3 bucket",
  "s3:DeleteBucket": "Delete an S3 bucket",
  // DynamoDB
  "dynamodb:*": "Full access to all DynamoDB operations",
  "dynamodb:GetItem": "Read a single item from a DynamoDB table",
  "dynamodb:PutItem": "Write a single item to a DynamoDB table",
  "dynamodb:DeleteItem": "Delete a single item from a DynamoDB table",
  "dynamodb:UpdateItem": "Update attributes of an item in a DynamoDB table",
  "dynamodb:Query": "Query items from a DynamoDB table using a key condition",
  "dynamodb:Scan": "Scan all items in a DynamoDB table",
  "dynamodb:BatchGetItem": "Read multiple items from DynamoDB tables in a batch",
  "dynamodb:BatchWriteItem": "Write or delete multiple items in DynamoDB tables in a batch",
  // Lambda
  "lambda:*": "Full access to all Lambda operations",
  "lambda:InvokeFunction": "Invoke a Lambda function",
  "lambda:GetFunction": "Get configuration information for a Lambda function",
  "lambda:ListFunctions": "List all Lambda functions",
  "lambda:CreateFunction": "Create a new Lambda function",
  // SQS
  "sqs:*": "Full access to all SQS operations",
  "sqs:SendMessage": "Send a message to an SQS queue",
  "sqs:ReceiveMessage": "Receive messages from an SQS queue",
  "sqs:DeleteMessage": "Delete a message from an SQS queue",
  "sqs:GetQueueUrl": "Get the URL of an SQS queue",
  // SNS
  "sns:*": "Full access to all SNS operations",
  "sns:Publish": "Publish a message to an SNS topic",
  "sns:Subscribe": "Subscribe an endpoint to an SNS topic",
  // IAM
  "iam:*": "Full access to all IAM operations",
  "iam:PassRole": "Pass an IAM role to an AWS service",
  "iam:GetRole": "Get information about an IAM role",
  "iam:ListRoles": "List all IAM roles",
  // STS
  "sts:AssumeRole": "Assume an IAM role to obtain temporary credentials",
  "sts:GetCallerIdentity": "Get details about the calling IAM identity",
  // CloudWatch / Logs
  "logs:*": "Full access to all CloudWatch Logs operations",
  "logs:CreateLogGroup": "Create a new CloudWatch log group",
  "logs:CreateLogStream": "Create a new log stream within a log group",
  "logs:PutLogEvents": "Upload log events to a CloudWatch log stream",
  "logs:GetLogEvents": "Read log events from a CloudWatch log stream",
  "logs:DescribeLogStreams": "List log streams within a log group",
  // Bedrock
  "bedrock:*": "Full access to all Bedrock operations",
  "bedrock:InvokeModel": "Invoke a Bedrock foundation model",
  "bedrock:InvokeModelWithResponseStream": "Invoke a Bedrock model with streaming response",
  "bedrock:ListFoundationModels": "List available Bedrock foundation models",
  // Secrets Manager
  "secretsmanager:GetSecretValue": "Retrieve the value of a secret",
  "secretsmanager:CreateSecret": "Create a new secret",
  "secretsmanager:PutSecretValue": "Store a new value for a secret",
  "secretsmanager:DeleteSecret": "Delete a secret",
  // EC2 (common)
  "ec2:DescribeInstances": "List and describe EC2 instances",
  "ec2:DescribeVpcs": "List and describe VPCs",
  "ec2:DescribeSubnets": "List and describe subnets",
  "ec2:DescribeSecurityGroups": "List and describe security groups",
  // KMS
  "kms:Encrypt": "Encrypt data using a KMS key",
  "kms:Decrypt": "Decrypt data using a KMS key",
  "kms:GenerateDataKey": "Generate a data encryption key from a KMS key",
};

function getActionDescription(action: string): string | undefined {
  if (ACTION_DESCRIPTIONS[action]) return ACTION_DESCRIPTIONS[action];
  // Try matching service:* if specific action not found
  const service = action.split(":")[0];
  if (action.endsWith("*") && !ACTION_DESCRIPTIONS[action]) {
    return `All ${service} operations matching ${action}`;
  }
  // Provide a generic description based on the action name
  const parts = action.split(":");
  if (parts.length === 2) {
    return `${parts[0]} ${parts[1]} operation`;
  }
  return undefined;
}

interface PolicyViewerProps {
  policy: PolicyDocument;
}

export function PolicyViewer({ policy }: PolicyViewerProps) {
  if (!policy.Statement || policy.Statement.length === 0) {
    return (
      <p className="text-xs text-muted-foreground italic">No policy statements</p>
    );
  }

  const toArray = (value: string | string[]): string[] =>
    Array.isArray(value) ? value : [value];

  return (
    <div className="space-y-2">
      {policy.Statement.map((stmt, i) => (
        <div
          key={stmt.Sid ?? i}
          className="rounded border bg-input-bg p-3 text-xs space-y-2"
        >
          <div className="flex items-center gap-2">
            {stmt.Sid && (
              <span className="font-medium">{stmt.Sid}</span>
            )}
            <span
              className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-medium ${
                stmt.Effect === "Allow"
                  ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                  : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400"
              }`}
            >
              {stmt.Effect}
            </span>
          </div>
          <div className="space-y-0.5">
            <span className="text-muted-foreground">Actions</span>
            <ul className="list-none space-y-0.5 pl-2">
              {toArray(stmt.Action).map((action) => {
                const desc = getActionDescription(action);
                return (
                  <li key={action} className="font-mono" title={desc}>
                    <span className={desc ? "underline decoration-dotted decoration-muted-foreground/50 cursor-help" : ""}>
                      {action}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="space-y-0.5">
            <span className="text-muted-foreground">Resources</span>
            <ul className="list-none space-y-0.5 pl-2">
              {toArray(stmt.Resource).map((resource) => (
                <li key={resource} className="font-mono break-all">{resource}</li>
              ))}
            </ul>
          </div>
        </div>
      ))}
    </div>
  );
}
