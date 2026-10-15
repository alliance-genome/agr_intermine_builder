#!/usr/bin/env bash
# create_mine_query_healthchecks.sh - Route53 health check + CloudWatch alarm per mine that runs a real query.
#
# The existing HealthCheck-<Mine> checks hit /service/version, which answers even when queries fail.
# These run a 1-row PathQuery through CloudFront and pass only if the JSON says "wasSuccessful":true,
# so a dead DB connection pool or an edge rule that breaks /service/query shows up.
#
#   scripts/create_mine_query_healthchecks.sh            # create missing checks + alarms
#   scripts/create_mine_query_healthchecks.sh --dry-run  # print what would be created
#
# Alarms notify SNS intermine-alerts (email) and alliance-alerts-warning (Slack); they do not page
# the incident-response topic the /service/version alarms use. ALARM only, no OK actions.
set -euo pipefail

# alliancemine, yeastmine, flymine and wormmine fetch query.xsd through the WAF on every query; checks on them
# tripped WAF rule 21 and blocked all their queries (docs/INCIDENT_2026_10_14_QUERY_HEALTHCHECKS.md).
MINES="mousemine"
QUERY='%3Cquery%20model%3D%22genomic%22%20view%3D%22Organism.taxonId%22/%3E'   # <query model="genomic" view="Organism.taxonId"/>
SEARCH='"wasSuccessful":true'
TOPICS="arn:aws:sns:us-east-1:100225593120:intermine-alerts arn:aws:sns:us-east-1:100225593120:alliance-alerts-warning"
DRY=${1:-}

for mine in $MINES; do
    host="$mine.alliancegenome.org"
    path="/$mine/service/query/results?query=$QUERY&format=json&size=1"
    name="HealthCheck-${mine}-query"

    if [ "$(curl -s --max-time 30 "https://$host$path" | grep -c "$SEARCH")" = 0 ]; then
        echo "$mine: query does not return $SEARCH right now - check the mine before creating the alarm" >&2
    fi

    id=$(aws route53 list-health-checks --query \
        "HealthChecks[?HealthCheckConfig.FullyQualifiedDomainName=='$host' && HealthCheckConfig.Type=='HTTPS_STR_MATCH'].Id | [0]" \
        --output text)
    if [ "$id" = None ] || [ -z "$id" ]; then
        if [ "$DRY" = --dry-run ]; then
            echo "would create: $name https://$host$path"; continue
        fi
        id=$(aws route53 create-health-check --caller-reference "$name-$(date +%s)" --health-check-config "$(cat <<JSON
{"Type": "HTTPS_STR_MATCH", "FullyQualifiedDomainName": "$host", "Port": 443, "ResourcePath": "$path",
 "SearchString": $(printf '%s' "$SEARCH" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))'),
 "RequestInterval": 30, "FailureThreshold": 3, "EnableSNI": true}
JSON
)" --query HealthCheck.Id --output text)
        aws route53 change-tags-for-resource --resource-type healthcheck --resource-id "$id" \
            --add-tags Key=Name,Value="$name"
        echo "$mine: created health check $id"
    else
        echo "$mine: health check $id already exists"
    fi
    [ "$DRY" = --dry-run ] && continue

    # Route53 health-check metrics live in us-east-1; Minimum < 1 over 2 x 60 s = failing for 2 minutes.
    # notBreaching: a new check has no datapoints for its first minutes, and breaching fired the alarm at creation.
    # shellcheck disable=SC2086
    aws cloudwatch put-metric-alarm --region us-east-1 --alarm-name "$name" \
        --alarm-description "$mine: a 1-row query through CloudFront did not return wasSuccessful=true" \
        --namespace AWS/Route53 --metric-name HealthCheckStatus --dimensions Name=HealthCheckId,Value="$id" \
        --statistic Minimum --period 60 --evaluation-periods 2 --threshold 1 \
        --comparison-operator LessThanThreshold --treat-missing-data notBreaching \
        --alarm-actions $TOPICS
    echo "$mine: alarm $name set"
done
