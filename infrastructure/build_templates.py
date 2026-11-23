"""Generates the SAM templates (level1-2, level3 ... level7) from shared fragments.
Run: python3 build_templates.py   (outputs level*.yaml next to this file)"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
HEAD = """AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: @@DESC@@

Globals:
  Function:
    Runtime: python3.12
    Timeout: 25            # keep below the ~30 s API Gateway integration limit
    MemorySize: 512
    Architectures: [arm64]
    Tracing: Active
"""
SECRET = """        - Statement:
            - Effect: Allow
              Action: secretsmanager:GetSecretValue
              Resource: !Ref AnthropicSecretArn
"""
ENVBASE = """          ANTHROPIC_SECRET_ARN: !Ref AnthropicSecretArn
          CLAUDE_MODEL: !Ref ClaudeModel
          LOG_LEVEL: INFO
"""
BASE_PARAMS = """
Parameters:
  AnthropicSecretArn:
    Type: String
    Description: 'ARN of the Secrets Manager secret holding a JSON object with key api_key' 
  ClaudeModel:
    Type: String
    Description: A currently supported Anthropic model ID (check the Anthropic docs)
  AllowedOrigin:
    Type: String
    Default: http://localhost:8080
    Description: Exact origin of the website (scheme + host, no trailing slash)
"""
AUTH_PARAMS = """  CognitoDomainPrefix:
    Type: String
    Description: Globally unique prefix for the Cognito Hosted UI domain
  CallbackUrl:
    Type: String
    Default: http://localhost:8080/
    Description: Where Cognito redirects after login (must match the site URL exactly)
"""
COGNITO = """
  UserPool:
    Type: AWS::Cognito::UserPool
    Properties:
      UsernameAttributes: [email]
      AutoVerifiedAttributes: [email]
      AdminCreateUserConfig:
        AllowAdminCreateUserOnly: true        # invite-only; users cannot self-register
      Policies:
        PasswordPolicy: {MinimumLength: 12, RequireLowercase: true, RequireUppercase: true, RequireNumbers: true, RequireSymbols: false}
      Schema:
        - Name: tenant_id
          AttributeDataType: String
          Mutable: true
  UserPoolDomain:
    Type: AWS::Cognito::UserPoolDomain
    Properties:
      Domain: !Ref CognitoDomainPrefix
      UserPoolId: !Ref UserPool
  UserPoolClient:
    Type: AWS::Cognito::UserPoolClient
    Properties:
      UserPoolId: !Ref UserPool
      GenerateSecret: false
      AllowedOAuthFlowsUserPoolClient: true
      AllowedOAuthFlows: [code]
      AllowedOAuthScopes: [openid, email, profile]
      SupportedIdentityProviders: [COGNITO]
      CallbackURLs: [!Ref CallbackUrl]
      LogoutURLs: [!Ref CallbackUrl]
      ReadAttributes: [email, custom:tenant_id]
      WriteAttributes: [email]                # users can never set their own tenant
"""
def api(auth, extra_throttle=""):
    a = """
  Api:
    Type: AWS::Serverless::HttpApi
    Properties:
      CorsConfiguration:
        AllowOrigins: [!Ref AllowedOrigin]
        AllowHeaders: [content-type, authorization, idempotency-key]
        AllowMethods: [GET, POST, DELETE, OPTIONS]
      DefaultRouteSettings:
        ThrottlingBurstLimit: 20
        ThrottlingRateLimit: 10
"""
    if auth:
        a += """      Auth:
        DefaultAuthorizer: Jwt
        Authorizers:
          Jwt:
            IdentitySource: $request.header.Authorization
            JwtConfiguration:
              issuer: !Sub https://cognito-idp.${AWS::Region}.amazonaws.com/${UserPool}
              audience: [!Ref UserPoolClient]
"""
    return a
def table(name, key2=True, ttl=False, rk="sk", hk="pk"):
    t = f"""
  {name}:
    Type: AWS::DynamoDB::Table
    Properties:
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - {{AttributeName: {hk}, AttributeType: S}}
"""
    if key2:
        t += f"        - {{AttributeName: {rk}, AttributeType: S}}\n"
    t += f"      KeySchema:\n        - {{AttributeName: {hk}, KeyType: HASH}}\n"
    if key2:
        t += f"        - {{AttributeName: {rk}, KeyType: RANGE}}\n"
    t += "      SSESpecification: {SSEEnabled: true}\n      PointInTimeRecoverySpecification: {PointInTimeRecoveryEnabled: true}\n"
    if ttl:
        t += "      TimeToLiveSpecification: {AttributeName: expires, Enabled: true}\n"
    return t
def crud(t): return f"        - DynamoDBCrudPolicy: {{TableName: !Ref {t}}}\n"
def fn(name, handler, env="", policies="", events="", extra=""):
    return f"""
  {name}:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: ../backend/
      Handler: {handler}
{extra}      Environment:
        Variables:
{ENVBASE}{env}      Policies:
{SECRET}{policies}      Events:
{events}"""
def ev(name, route, method):
    return f"""        {name}:
          Type: HttpApi
          Properties: {{ApiId: !Ref Api, Path: "{route}", Method: {method}}}
"""
OUT = """
Outputs:
  ApiUrl:
    Value: !Sub https://${Api}.execute-api.${AWS::Region}.amazonaws.com
"""
AUTH_OUT = """  UserPoolId:
    Value: !Ref UserPool
  UserPoolClientId:
    Value: !Ref UserPoolClient
  CognitoDomain:
    Value: !Sub https://${CognitoDomainPrefix}.auth.${AWS::Region}.amazoncognito.com
"""
def build(file, desc, params="", body="", outs=""):
    s = HEAD.replace("@@DESC@@", desc) + BASE_PARAMS + params + "\nResources:" + body + OUT + outs
    open(os.path.join(HERE, file), "w").write(s)

# ---- Level 1 / 2 -----------------------------------------------------------
l12 = f"""
  Level:
    Type: String
    Default: '1'
    AllowedValues: ['1', '2']
    Description: 1 = single question, 2 = multi-turn (history supplied by browser)
"""
b = api(False) + fn("ChatFn", "!If [IsLevel2, level2_conversation.handler.lambda_handler, level1_basic.handler.lambda_handler]", "", "", ev("Chat", "/chat", "POST"))
body = b.replace("      Handler: !If [IsLevel2, level2_conversation.handler.lambda_handler, level1_basic.handler.lambda_handler]",
                 "      Handler: !If [IsLevel2, level2_conversation.handler.lambda_handler, level1_basic.handler.lambda_handler]")
s = HEAD.replace("@@DESC@@", "Claude chatbot - Level 1 (basic Q&A) / Level 2 (multi-turn)") + BASE_PARAMS + l12 + "\nConditions:\n  IsLevel2: !Equals [!Ref Level, '2']\n\nResources:" + body + OUT
open(os.path.join(HERE, "level1-2.yaml"), "w").write(s)

# ---- Level 3 ---------------------------------------------------------------
L3_ENV = "          SESSIONS_TABLE: !Ref SessionsTable\n          MESSAGES_TABLE: !Ref MessagesTable\n"
L3_POL = crud("SessionsTable") + crud("MessagesTable")
L3_EVENTS = ev("Chat", "/chat", "POST") + ev("List", "/chats", "GET") + ev("Get", "/chats/{chatId}", "GET") + ev("Del", "/chats/{chatId}", "DELETE")
build("level3.yaml", "Claude chatbot - Level 3 (Cognito login + DynamoDB history)", AUTH_PARAMS,
      COGNITO + api(True) + table("SessionsTable") + table("MessagesTable", ttl=False)
      + fn("ChatFn", "level3_chat.handler.lambda_handler", L3_ENV, L3_POL, L3_EVENTS), AUTH_OUT)

# ---- Level 4 ---------------------------------------------------------------
P4 = AUTH_PARAMS + "  KnowledgeBaseId:\n    Type: String\n    Description: Bedrock Knowledge Base ID (created manually; see the guide)\n"
DOCS = """
  DocBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault: {SSEAlgorithm: AES256}
      PublicAccessBlockConfiguration: {BlockPublicAcls: true, BlockPublicPolicy: true, IgnorePublicAcls: true, RestrictPublicBuckets: true}
      VersioningConfiguration: {Status: Enabled}
"""
POL4 = """        - Statement:
            - Effect: Allow
              Action: bedrock:Retrieve
              Resource: !Sub arn:aws:bedrock:${AWS::Region}:${AWS::AccountId}:knowledge-base/${KnowledgeBaseId}
"""
build("level4.yaml", "Claude chatbot - Level 4 (RAG with Bedrock Knowledge Bases)", P4,
      COGNITO + api(True) + DOCS + fn("RagFn", "level4_rag.handler.lambda_handler", "          KNOWLEDGE_BASE_ID: !Ref KnowledgeBaseId\n", POL4, ev("Ask", "/ask", "POST")),
      AUTH_OUT + "  DocBucketName:\n    Value: !Ref DocBucket\n")

# ---- Level 5 ---------------------------------------------------------------
build("level5.yaml", "Claude chatbot - Level 5 (tool-calling agent with approval)", AUTH_PARAMS,
      COGNITO + api(True) + table("OrdersTable", rk="order_id", hk="customer_id") + table("AgentTable", ttl=True)
      + fn("AgentFn", "level5_agent.handler.lambda_handler",
           "          ORDERS_TABLE: !Ref OrdersTable\n          AGENT_TABLE: !Ref AgentTable\n",
           crud("OrdersTable") + crud("AgentTable"), ev("Agent", "/agent", "POST") + ev("Approve", "/agent/approve", "POST")),
      AUTH_OUT + "  OrdersTable:\n    Value: !Ref OrdersTable\n")

# ---- Level 6 ---------------------------------------------------------------
P6 = AUTH_PARAMS + "  AlertEmail:\n    Type: String\n    Description: Email that receives alarm notifications (confirm the SNS subscription)\n  DailyLimit:\n    Type: Number\n    Default: 100\n    Description: Max chat requests per user per day\n"
Q6 = """
  JobsDlq:
    Type: AWS::SQS::Queue
    Properties: {MessageRetentionPeriod: 1209600}
  JobsQueue:
    Type: AWS::SQS::Queue
    Properties:
      VisibilityTimeout: 720                   # 6x the worker timeout (AWS guidance)
      RedrivePolicy: {deadLetterTargetArn: !GetAtt JobsDlq.Arn, maxReceiveCount: 3}
  AlertTopic:
    Type: AWS::SNS::Topic
    Properties:
      Subscription: [{Protocol: email, Endpoint: !Ref AlertEmail}]
  DlqAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmDescription: Messages are stuck in the dead-letter queue
      Namespace: AWS/SQS
      MetricName: ApproximateNumberOfMessagesVisible
      Dimensions: [{Name: QueueName, Value: !GetAtt JobsDlq.QueueName}]
      Statistic: Maximum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      AlarmActions: [!Ref AlertTopic]
  ChatErrorAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmDescription: Chat Lambda errors
      Namespace: AWS/Lambda
      MetricName: Errors
      Dimensions: [{Name: FunctionName, Value: !Ref ChatFn}]
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 5
      ComparisonOperator: GreaterThanOrEqualToThreshold
      TreatMissingData: notBreaching
      AlarmActions: [!Ref AlertTopic]
  ApiServerErrorAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmDescription: API 5xx responses
      Namespace: AWS/ApiGateway
      MetricName: 5xx
      Dimensions: [{Name: ApiId, Value: !Ref Api}]
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 5
      ComparisonOperator: GreaterThanOrEqualToThreshold
      TreatMissingData: notBreaching
      AlarmActions: [!Ref AlertTopic]
"""
chat6 = fn("ChatFn", "level3_chat.handler.lambda_handler",
           L3_ENV + "          QUOTA_TABLE: !Ref QuotaTable\n          DAILY_LIMIT: !Ref DailyLimit\n",
           L3_POL + crud("QuotaTable"), L3_EVENTS, "      ReservedConcurrentExecutions: 10\n")
jobs6 = fn("JobsFn", "level6_scale.jobs.lambda_handler",
           "          JOBS_TABLE: !Ref JobsTable\n          QUEUE_URL: !Ref JobsQueue\n          QUOTA_TABLE: !Ref QuotaTable\n          DAILY_LIMIT: !Ref DailyLimit\n",
           crud("JobsTable") + crud("QuotaTable") + "        - SQSSendMessagePolicy: {QueueName: !GetAtt JobsQueue.QueueName}\n",
           ev("Create", "/jobs", "POST") + ev("Get", "/jobs/{jobId}", "GET"))
worker6 = fn("WorkerFn", "level6_scale.worker.lambda_handler", "          JOBS_TABLE: !Ref JobsTable\n", crud("JobsTable"),
             """        Queue:
          Type: SQS
          Properties:
            Queue: !GetAtt JobsQueue.Arn
            BatchSize: 1
            FunctionResponseTypes: [ReportBatchItemFailures]
""", "      Timeout: 120\n      ReservedConcurrentExecutions: 5\n")
# a function-level Timeout placed before Environment overrides Globals
build("level6.yaml", "Claude chatbot - Level 6 (quotas, async jobs, DLQ, alarms)", P6,
      COGNITO + api(True) + table("SessionsTable") + table("MessagesTable") + table("QuotaTable", key2=False, ttl=True)
      + table("JobsTable", ttl=True) + Q6 + chat6 + jobs6 + worker6, AUTH_OUT + "  AlertTopicArn:\n    Value: !Ref AlertTopic\n")

# ---- Level 7 ---------------------------------------------------------------
POL7 = """        - Statement:
            - Effect: Allow
              Action: [bedrock:InvokeModel, bedrock:Converse]
              Resource:
                - !Sub arn:aws:bedrock:*::foundation-model/*
                - !Sub arn:aws:bedrock:*:${AWS::AccountId}:inference-profile/*
""" + crud("TenantsTable") + crud("UsageTable") + crud("AuditTable")
ENV7 = "          TENANTS_TABLE: !Ref TenantsTable\n          USAGE_TABLE: !Ref UsageTable\n          AUDIT_TABLE: !Ref AuditTable\n          ALLOW_UNREGISTERED_TENANTS: 'false'\n"
build("level7.yaml", "Claude chatbot - Level 7 (governed multi-tenant AI gateway)", AUTH_PARAMS,
      COGNITO + api(True, ) + table("TenantsTable", key2=False) + table("UsageTable", key2=False, ttl=True) + table("AuditTable", ttl=True)
      + fn("GatewayFn", "level7_platform.handler.lambda_handler", ENV7, POL7, ev("Chat", "/v1/chat", "POST")),
      AUTH_OUT + "  TenantsTable:\n    Value: !Ref TenantsTable\n  AuditTable:\n    Value: !Ref AuditTable\n")
print("templates written")
