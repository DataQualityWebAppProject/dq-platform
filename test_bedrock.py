import boto3
import json

client = boto3.client('bedrock-runtime', region_name='us-east-1')

try:
    response = client.invoke_model(
        modelId='amazon.nova-lite-v1:0',
        contentType='application/json',
        accept='application/json',
        body=json.dumps({
            'inferenceConfig': {'maxTokens': 50},
            'messages': [{'role': 'user', 'content': [{'text': 'Say hello in one word'}]}]
        })
    )
    result = json.loads(response['body'].read())
    print("SUCCESS:", result['output']['message']['content'][0]['text'])
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
