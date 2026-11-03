#!/usr/bin/env bash
# ci-deploy.sh — the one command the GitHub PRODUCTION workflows run over SSH.
#
#   sudo /usr/bin/bash ci-deploy.sh app  main [--backend-only|--frontend-only] [--migrate]
#   sudo /usr/bin/bash ci-deploy.sh nidp main [--migrate] [--install-cron]
#
# Syncs the VM's checkout to origin/main with the VM's read-only deploy key, then runs the
# matching deploy script from that checkout. The CI user's sudo rights are limited to this
# script (/etc/sudoers.d/92-ci-deploy-prod, written by bootstrap.sh).
#
# Production deploys ONLY `main` (feat/* → dev → main by PR). A hotfix goes through a PR, not a
# workflow input. Both stacks share one checkout, so the two targets are serialized with a lock.
#
# The body is one function called on the last line: bash has then parsed the whole file
# before the `git reset` below can replace it on disk.

set -euo pipefail

main() {
    local target="${1:-}" branch="${2:-}"
    [[ "$target" == "app" || "$target" == "nidp" ]] && [[ -n "$branch" ]] \
        || { echo "usage: $0 app|nidp main [deploy flags]" >&2; exit 2; }
    shift 2
    [[ "$branch" == "main" ]] || { echo "[ci-deploy] FATAL: production deploys only 'main' (got '${branch}')" >&2; exit 2; }
    [[ $EUID -eq 0 ]] || { echo "[ci-deploy] FATAL: run with sudo" >&2; exit 1; }

    local repo=/opt/nivesh/repo key=/opt/nivesh/.ssh/id_ed25519
    [[ -d "${repo}/.git" ]] || { echo "[ci-deploy] FATAL: ${repo} missing — run bootstrap.sh" >&2; exit 1; }

    exec 9>/run/lock/nivesh-prod-deploy.lock
    echo "[ci-deploy] waiting for the deploy lock..."
    flock 9

    echo "[ci-deploy] target=${target} branch=${branch} flags=$*"
    export GIT_SSH_COMMAND="ssh -i ${key} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
    local git=(git -c "safe.directory=${repo}" -C "$repo")
    "${git[@]}" fetch --quiet origin "$branch"
    "${git[@]}" checkout --quiet "$branch"
    "${git[@]}" reset --hard --quiet "origin/${branch}"

    if [[ "$target" == "app" ]]; then
        bash "${repo}/deploy/cloudpe-prod/deploy-app.sh" "$branch" "$@"
        # What the old backend workflow did as a separate step after a backend deploy.
        if [[ " $* " != *" --frontend-only "* ]]; then
            echo "[ci-deploy] Clearing performance caches..."
            docker exec nivesh-backend python -m scripts.clear_performance_caches
        fi
    else
        bash "${repo}/deploy/cloudpe-prod/deploy-nidp.sh" "$branch" "$@"
    fi
    echo "[ci-deploy] OK"
}

main "$@"; exit
