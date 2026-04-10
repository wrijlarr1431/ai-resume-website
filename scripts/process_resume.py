import boto3
import json
import os
import uuid
from datetime import datetime, timezone

BUCKET_NAME = os.environ["BUCKET_NAME"]
ENVIRONMENT = os.environ.get("ENVIRONMENT", "beta")
COMMIT_SHA  = os.environ.get("COMMIT_SHA", str(uuid.uuid4()))
AWS_REGION  = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID    = os.environ.get("MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

bedrock  = boto3.client("bedrock-runtime", region_name=AWS_REGION)
s3       = boto3.client("s3", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

deployment_table = dynamodb.Table("DeploymentTracking")
analytics_table  = dynamodb.Table("ResumeAnalytics")


def call_bedrock(prompt: str) -> str:
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": prompt}]
    })
    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json"
    )
    return json.loads(response["body"].read())["content"][0]["text"]


# Read resume
print("Reading resume.md...")
with open("resume.md", "r") as f:
    resume_content = f.read()

# AI Call 1: Generate HTML
print("Generating HTML resume...")
html_output = call_bedrock(f"""
Convert the following Markdown resume into a complete, professional HTML page.
Use clean semantic HTML5 with inline CSS. Make it ATS-friendly and mobile-responsive.
Return ONLY the full HTML document, no explanation.

Resume:
{resume_content}
""")

with open("index.html", "w") as f:
    f.write(html_output)
print("index.html generated.")

# AI Call 2: ATS Analysis
print("Analyzing resume for ATS...")
analysis_raw = call_bedrock(f"""
Analyze this resume and return ONLY a valid JSON object with this structure:
{{
  "ats_score": <0-100>,
  "word_count": <integer>,
  "readability_score": <0-100>,
  "keywords": [<top 10 keywords>],
  "missing_sections": [<missing sections>],
  "strengths": [<3 strengths>],
  "improvements": [<3 improvements>]
}}

Resume:
{resume_content}
""")

analysis_clean = analysis_raw.strip().strip("```json").strip("```").strip()
analysis = json.loads(analysis_clean)
print(f"ATS Score: {analysis['ats_score']}")

# Upload to S3
s3_key = f"{ENVIRONMENT}/index.html"
print(f"Uploading to s3://{BUCKET_NAME}/{s3_key}...")
s3.upload_file(
    "index.html", BUCKET_NAME, s3_key,
    ExtraArgs={"ContentType": "text/html"}
)
s3_url = f"http://{BUCKET_NAME}.s3-website-{AWS_REGION}.amazonaws.com/{s3_key}"
print(f"Uploaded: {s3_url}")

# Write to DynamoDB
timestamp = datetime.now(timezone.utc).isoformat()

deployment_table.put_item(Item={
    "deploymentId": COMMIT_SHA,
    "environment":  ENVIRONMENT,
    "status":       "success",
    "s3Url":        s3_url,
    "modelUsed":    MODEL_ID,
    "timestamp":    timestamp
})

analytics_table.put_item(Item={
    "analysisId":       COMMIT_SHA,
    "environment":      ENVIRONMENT,
    "atsScore":         analysis["ats_score"],
    "wordCount":        analysis["word_count"],
    "readabilityScore": analysis["readability_score"],
    "keywords":         analysis["keywords"],
    "missingSections":  analysis["missing_sections"],
    "strengths":        analysis["strengths"],
    "improvements":     analysis["improvements"],
    "timestamp":        timestamp
})

print(f"\n✅ Done! Environment: {ENVIRONMENT} | ATS Score: {analysis['ats_score']}/100")
print(f"   URL: {s3_url}")