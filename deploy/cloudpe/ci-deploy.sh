#!/usr/bin/env bash
# ci-deploy.sh — the one command the GitHub staging workflows run over SSH.
#
#   sudo /usr/bin/bash ci-deploy.sh app  <branch> [--backend-only|--frontend-only] [--migrate]
#   sudo /usr/bin/bash ci-deploy.sh nidp <branch> [--migrate]
#
# Syncs the VM's checkout to origin/<branch> with the VM's read-only deploy key,
# then runs that checkout's deploy.sh. The CI user's sudo rights are limited to
# this script (see README, "CI"), so everything a workflow may do is here.
#
# The body is one function called on the last line: bash has then parsed the
# whole file before the `git reset` below can replace it on disk.

set -euo pipefail

main() {
    local target="${1:-}" branch="${2:-}"
    [[ "$target" == "app" || "$target" == "nidp" ]] && [[ -n "$branch" ]] \
        || { echo "usage: $0 app|nidp <branch> [deploy.sh flags]" >&2; exit 2; }
    shift 2
    [[ "$branch" =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "[ci-deploy] FATAL: unsafe branch name" >&2; exit 2; }
    [[ $EUID -eq 0 ]] || { echo "[ci-deploy] FATAL: run with sudo" >&2; exit 1; }

    local repo key
    if [[ "$target" == "app" ]]; then
        repo=/opt/nivesh-staging/repo
        key=/opt/nivesh-staging/.ssh/id_ed25519
    else
        repo=/opt/nidp/dev-repo/nivesh.ai
        key=/opt/nidp/.ssh/id_ed25519
    fi
    [[ -d "${repo}/.git" ]] || { echo "[ci-deploy] FATAL: ${repo} missing — run ${target}/bootstrap.sh" >&2; exit 1; }

    echo "[ci-deploy] target=${target} branch=${branch} flags=$*"
    export GIT_SSH_COMMAND="ssh -i ${key} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
    local git=(git -c "safe.directory=${repo}" -C "$repo")
    "${git[@]}" fetch --quiet origin "$branch"
    "${git[@]}" checkout --quiet "$branch"
    "${git[@]}" reset --hard --quiet "origin/${branch}"

    bash "${repo}/deploy/cloudpe/${target}/deploy.sh" "$branch" "$@"

    # What the old backend workflow did as separate steps after a backend deploy.
    if [[ "$target" == "app" && " $* " != *" --frontend-only "* ]]; then
        install -m 644 -o root -g root "${repo}/deploy/nivesh-staging/cache-clear.cron" \
            /etc/cron.d/nivesh-staging-cache-clear
        echo "[ci-deploy] Clearing performance caches..."
        docker exec nivesh-staging-app-backend python -m scripts.clear_performance_caches
    fi
    echo "[ci-deploy] OK"
}

main "$@"; exit
