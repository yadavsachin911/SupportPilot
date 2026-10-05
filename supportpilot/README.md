# SupportPilot: AI ticket triage (REST + Kafka + AI agent + n8n + API Gateway + AWS)

```
Client -> API Gateway -> REST API (FastAPI) -> Kafka: ticket.created
                                                   |
                                          AI agent worker (tools = REST APIs)
                                                   |
                                             Kafka: ticket.triaged
                                                   |
                                        n8n (Slack, approval, email, PATCH status)
```

## Run locally (no AWS, no API key)
```bash
cp .env.example .env
docker compose up --build          # Redpanda, API, agent (mock LLM), n8n
./scripts/demo.sh                  # sends 3 sample tickets
curl localhost:8000/tickets/<ticket_id>
```
Interactive API docs: http://localhost:8000/docs

### Wire up n8n (one-time, http://localhost:5678)
1. Create a **Kafka** credential: Client ID `n8n`, Brokers `redpanda:9092`, SSL off, Authentication off.
2. Import `n8n/supportpilot-workflow.json`, open **Kafka Trigger**, select that credential, then **Activate**.
3. Expected results after `demo.sh`:
   - "Where is my order?" -> `auto_replied`
   - "Refund please" -> `awaiting_approval`. Open the approve URL from the Wait node's execution
     (or Slack, if `SLACK_WEBHOOK_URL` is set) -> `refund_approved`
   - "URGENT: production down" -> `escalated`

### Use the real model
Set `MOCK_LLM=false` and `ANTHROPIC_API_KEY=...` in `.env`, then `docker compose up -d agent`.
For Bedrock instead: `MOCK_LLM=false`, `LLM_PROVIDER=bedrock`, `AWS_REGION=...`, and set `AGENT_MODEL` to your Bedrock model ID.

## Tests
```bash
cd api   && pip install -r requirements-dev.txt && pytest
cd agent && pip install -r requirements-dev.txt && pytest
```

## Deploy to AWS
1. `infra/terraform`: creates MSK Serverless (IAM auth), Cognito, Secrets Manager secret, API Gateway
   (JWT auth, throttling, VPC Link). It **does not** create the VPC, ECS cluster/services, or the internal ALB;
   pass those in as variables (or ask Cursor to add them).
2. Create the three topics on MSK (`ticket.created`, `ticket.triaged`, `ticket.created.dlq`).
3. Build and push the `api` and `agent` images to ECR and run them on ECS Fargate. Task env:
   `KAFKA_BROKERS=<output kafka_bootstrap>`, `KAFKA_AUTH=iam`, `AWS_REGION`, `INTERNAL_API_URL=<internal ALB>`,
   `MOCK_LLM=false`. Inject the Anthropic key from Secrets Manager. Give each task role
   `kafka-cluster:*` permissions on the cluster, topics, and groups it needs.
4. Replace `store.py` (SQLite) with DynamoDB/RDS.
5. Run n8n on ECS with Postgres. In the workflow, swap the **Send reply** HTTP node for the AWS SES node.
   n8n talks to the internal ALB directly. Only `POST /tickets` and `GET /tickets/{id}` are exposed publicly.

## Known gaps (deliberate for a starter)
- Save-then-publish in `POST /tickets` is a dual write; use the outbox pattern for production.
- `KAFKA_AUTH=iam` and the Terraform were **not** run against a real AWS account here; expect small adjustments.
- No agent eval set yet. Add 50 to 100 labeled tickets and score accuracy before trusting auto-replies.
- Scale the agent on consumer lag (add an ECS autoscaling policy on the MSK lag metric).
