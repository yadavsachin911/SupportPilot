#!/usr/bin/env bash
# Sends three sample tickets: auto-reply, refund approval, urgent escalation.
API=${API:-http://localhost:8000}
post() { curl -s -X POST "$API/tickets" -H 'content-type: application/json' -d "$1"; echo; }
post '{"customer_id":"C-100","customer_email":"a@example.com","subject":"Where is my order?","body":"My delivery has not arrived yet."}'
post '{"customer_id":"C-200","customer_email":"b@example.com","subject":"Refund please","body":"Item arrived damaged, I want a refund."}'
post '{"customer_id":"C-300","customer_email":"c@example.com","subject":"URGENT: production down","body":"We are locked out of our account."}'
echo "Check status: curl $API/tickets/<ticket_id>"
