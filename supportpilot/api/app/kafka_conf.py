"""Kafka client config. Local (Redpanda) = plaintext. AWS MSK Serverless = IAM auth."""
import os


def kafka_conf() -> dict:
    conf: dict = {"bootstrap.servers": os.environ["KAFKA_BROKERS"]}
    if os.getenv("KAFKA_AUTH") == "iam":
        from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

        region = os.environ["AWS_REGION"]

        def oauth_cb(_cfg):
            token, expiry_ms = MSKAuthTokenProvider.generate_auth_token(region)
            return token, expiry_ms / 1000

        conf.update(
            {
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "OAUTHBEARER",
                "oauth_cb": oauth_cb,
            }
        )
    return conf
