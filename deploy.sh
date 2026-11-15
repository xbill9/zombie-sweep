#!/usr/bin/env bash
# Build the Lambda bundle, upload it, and deploy the stack. One command, run
# from a laptop: no build server, no pipeline.
#
#   ./deploy.sh            deploy (or update) the stack
#   ./deploy.sh run        start a sweep now and wait for it
set -euo pipefail
cd "$(dirname "$0")"

STACK=${STACK:-zombie-sweep}
REGION=${REGION:-us-east-1}
ZOMBIESCAN_REPO=${ZOMBIESCAN_REPO:-https://github.com/xbill9/zombiescan.git}
ZOMBIESCAN_REF=${ZOMBIESCAN_REF:-e7635e6e9d22ea2158bf3c09e25b1ef8df88c36b}
export AWS_REGION=$REGION

if [[ ${1:-} == run ]]; then
  ARN=$(aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='StateMachineArn'].OutputValue" --output text)
  EXEC=$(aws stepfunctions start-execution --state-machine-arn "$ARN" --query executionArn --output text)
  echo "started $EXEC"
  while :; do
    STATUS=$(aws stepfunctions describe-execution --execution-arn "$EXEC" --query status --output text)
    [[ $STATUS != RUNNING ]] && break
    sleep 3
  done
  aws stepfunctions describe-execution --execution-arn "$EXEC" \
    --query '{status:status,start:startDate,stop:stopDate,output:output}' --output json
  exit 0
fi

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
CODE_BUCKET="${STACK}-code-${ACCOUNT}-${REGION}"
if ! aws s3api head-bucket --bucket "$CODE_BUCKET" 2>/dev/null; then
  aws s3api create-bucket --bucket "$CODE_BUCKET" >/dev/null
  aws s3api put-public-access-block --bucket "$CODE_BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-lifecycle-configuration --bucket "$CODE_BUCKET" --lifecycle-configuration \
    '{"Rules":[{"ID":"expire","Status":"Enabled","Filter":{},"Expiration":{"Days":30}}]}' >/dev/null
fi

# Bundle: our three handlers plus zombiescan's engine at a pinned commit.
# boto3 comes from the Lambda runtime; zombiescan's other dependencies
# (click, rich) belong to its CLI, which the bundle does not include.
BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
git clone --quiet "$ZOMBIESCAN_REPO" "$BUILD/zs"
git -C "$BUILD/zs" checkout --quiet "$ZOMBIESCAN_REF"
mkdir "$BUILD/pkg"
cp functions/*.py "$BUILD/pkg/"
cp -r "$BUILD/zs/src/zombiescan" "$BUILD/pkg/zombiescan"
rm -f "$BUILD/pkg/zombiescan/cli.py" "$BUILD/pkg/zombiescan/report.py" "$BUILD/pkg/zombiescan/mcp_server.py"
find "$BUILD/pkg" -name __pycache__ -prune -exec rm -rf {} +
# Fixed timestamps and sorted entries: the same source gives the same zip,
# so an unchanged bundle keeps its key and CloudFormation sees no change.
python3 -I - "$BUILD/pkg" "$BUILD/bundle.zip" <<'PY'
import os, sys, zipfile
src, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(src):
        dirs.sort()
        for f in sorted(files):
            path = os.path.join(root, f)
            info = zipfile.ZipInfo(os.path.relpath(path, src), (2020, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, open(path, "rb").read())
PY
HASH=$(sha256sum "$BUILD/bundle.zip" | cut -c1-16)
KEY="bundle-${HASH}.zip"
aws s3 cp --quiet "$BUILD/bundle.zip" "s3://${CODE_BUCKET}/${KEY}"
echo "bundle s3://${CODE_BUCKET}/${KEY} ($(du -h "$BUILD/bundle.zip" | cut -f1))"

aws cloudformation deploy --stack-name "$STACK" --template-file template.yaml \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides CodeBucket="$CODE_BUCKET" CodeKey="$KEY"

aws cloudformation describe-stacks --stack-name "$STACK" \
  --query 'Stacks[0].Outputs' --output table
