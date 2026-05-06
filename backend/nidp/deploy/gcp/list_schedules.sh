#!/usr/bin/env bash
# list_schedules.sh — show all NIDP Cloud Scheduler triggers + their
# next-run times in a single table.
#
# Quick ops view: "is everything wired up and ready to fire?"
#
# Usage:
#   ./list_schedules.sh
set -uo pipefail

PROJECT="${GCP_PROJECT:-niveshdataintelligence}"
REGION="${GCP_REGION:-asia-south1}"

CYAN="\033[1;36m"; RESET="\033[0m"
echo -e "${CYAN}NIDP scheduler triggers — project=$PROJECT region=$REGION${RESET}"
echo

gcloud scheduler jobs list \
    --location="$REGION" --project="$PROJECT" \
    --filter='name~"nidp-cron-"' \
    --format='table(
        name.basename():label=NAME,
        schedule:label=CRON,
        timeZone:label=TZ,
        state:label=STATE,
        lastAttemptTime.date(format="%Y-%m-%d %H:%M"):label=LAST_FIRE,
        scheduleTime.date(format="%Y-%m-%d %H:%M"):label=NEXT_FIRE
    )'

echo
echo "  Manual fire:    gcloud scheduler jobs run nidp-cron-<job> --location=$REGION --project=$PROJECT"
echo "  Pause:          gcloud scheduler jobs pause nidp-cron-<job> ..."
echo "  Resume:         gcloud scheduler jobs resume nidp-cron-<job> ..."
echo "  Recreate all:   ./gcp_full_setup.sh --project=$PROJECT --only=9 --confirm"
