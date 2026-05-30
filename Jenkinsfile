// Jenkinsfile — Nivesh.ai CI pipeline + production deploy
//
// Runs on every push via GitHub webhook.
// Branch routing:
//   main → CI checks + deploy to PRODUCTION  (nivesh-app-vm + nidp-stack-vm)
//   dev  → CI checks only
//          STAGING deploys are handled by GitHub Actions:
//          .github/workflows/deploy-app-staging.yml
//          .github/workflows/deploy-nidp-staging.yml
//
// Required Jenkins credentials (Manage Jenkins → Credentials):
//   NIVESH_APP_VM_HOST — secret text, IP/hostname of nivesh-app-vm
//   nivesh-app-vm-ssh  — SSH private key for nivesh-app-vm
//   nidp-stack-vm-ssh  — SSH private key for nidp-stack-vm
//
// Run deploy/jenkins/configure-jenkins-staging.py on the VM to register all credentials.

pipeline {
    agent any

    environment {
        NIVESH_VM_HOST  = credentials('NIVESH_APP_VM_HOST')   // secret text
        NIDP_VM_HOST    = '34.93.60.254'
        SSH_USER        = 'sa_108611142161866522954'   // OS Login: nivesh-devops SA
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '30'))
        timeout(time: 45, unit: 'MINUTES')
        skipDefaultCheckout(false)
        ansiColor('xterm')
    }

    triggers {
        githubPush()
    }

    stages {

        // ── 1. Detect branch + changed paths ──────────────────────────────────
        stage('Changed Paths') {
            steps {
                script {
                    // GIT_BRANCH is set by Jenkins SCM checkout (e.g. "origin/main").
                    // Normalise to a plain branch name so `when { expression }` blocks
                    // can compare against 'main' and 'dev' without the remote prefix.
                    env.CURRENT_BRANCH = (env.GIT_BRANCH ?: '').replaceAll('^origin/', '')
                    if (!env.CURRENT_BRANCH) {
                        env.CURRENT_BRANCH = sh(
                            script: 'git rev-parse --abbrev-ref HEAD',
                            returnStdout: true
                        ).trim()
                    }

                    def changed = sh(
                        script: "git diff --name-only HEAD~1 HEAD 2>/dev/null || git diff --name-only HEAD",
                        returnStdout: true
                    ).trim()

                    env.DEPLOY_APP    = changed.find { it.startsWith('frontend/') || (it.startsWith('backend/') && !it.startsWith('backend/nidp/')) || it.startsWith('deploy/nivesh-app/') || it.startsWith('deploy/nivesh-staging/') } ? 'true' : 'false'
                    env.DEPLOY_NIDP   = changed.find { it.startsWith('backend/nidp/') } ? 'true' : 'false'
                    env.ONLY_FRONTEND = (!changed.find { it.startsWith('backend/') } && changed.find { it.startsWith('frontend/') }) ? 'true' : 'false'
                    env.ONLY_BACKEND  = (changed.find { it.startsWith('backend/') && !it.startsWith('backend/nidp/') } && !changed.find { it.startsWith('frontend/') }) ? 'true' : 'false'

                    echo """
Branch         : ${env.CURRENT_BRANCH}
Deploy App     : ${env.DEPLOY_APP}
Deploy NIDP    : ${env.DEPLOY_NIDP}
Frontend-only  : ${env.ONLY_FRONTEND}
Backend-only   : ${env.ONLY_BACKEND}
"""
                    // Skip the rest of the pipeline for branches other than main/dev.
                    if (env.CURRENT_BRANCH != 'main' && env.CURRENT_BRANCH != 'dev') {
                        echo "Branch '${env.CURRENT_BRANCH}' is not main or dev — skipping deploy."
                        currentBuild.result = 'NOT_BUILT'
                        return
                    }
                }
            }
        }

        // ── 2. CI — Backend syntax (both branches) ────────────────────────────
        stage('CI — Backend Syntax') {
            when {
                expression {
                    (env.CURRENT_BRANCH == 'main' || env.CURRENT_BRANCH == 'dev') &&
                    (env.DEPLOY_APP == 'true' || env.DEPLOY_NIDP == 'true')
                }
            }
            steps {
                sh '''
                    python3 -m py_compile backend/server.py
                    find backend -name "*.py" -not -path "*/__pycache__/*" \
                        -exec python3 -m py_compile {} +
                    echo "✅ Python syntax OK"
                '''
            }
        }

        // ── 3. CI — Frontend build (both branches, validates JS/CSS compile) ──
        // Uses a neutral placeholder URL — the real URL is baked in during
        // the on-VM build inside redeploy.sh / redeploy-staging.sh.
        stage('CI — Frontend Build') {
            when {
                expression {
                    (env.CURRENT_BRANCH == 'main' || env.CURRENT_BRANCH == 'dev') &&
                    env.DEPLOY_APP == 'true' && env.ONLY_BACKEND != 'true'
                }
            }
            steps {
                dir('frontend') {
                    sh '''
                        yarn install --frozen-lockfile --network-timeout 600000
                        REACT_APP_BACKEND_URL=https://niveshcopilot.com \
                          PUBLIC_URL=/v2 CI=false \
                          yarn build
                        echo "✅ Frontend build OK"
                    '''
                }
            }
        }

        // ════════════════════════════════════════════════════════════════════
        //  PRODUCTION DEPLOYS  (main branch only)
        // ════════════════════════════════════════════════════════════════════

        // ── 4a. Deploy nivesh-app-vm [PROD] ───────────────────────────────────
        stage('Deploy → nivesh-app-vm [prod]') {
            when {
                expression { env.CURRENT_BRANCH == 'main' && env.DEPLOY_APP == 'true' }
            }
            steps {
                script {
                    def flags = ''
                    if (env.ONLY_FRONTEND == 'true') flags = '--frontend-only'
                    if (env.ONLY_BACKEND  == 'true') flags = '--backend-only'

                    withCredentials([sshUserPrivateKey(
                        credentialsId: 'nivesh-app-vm-ssh',
                        keyFileVariable: 'SSH_KEY'
                    )]) {
                        sh """
                            ssh -i \$SSH_KEY -o StrictHostKeyChecking=no \\
                                ${env.SSH_USER}@${env.NIVESH_VM_HOST} \\
                                "sudo BRANCH=main bash /opt/nivesh/deploy/redeploy.sh ${flags}"
                        """
                    }
                }
            }
            post {
                success { echo "✅ nivesh-app-vm [prod] deploy complete." }
                failure { echo "❌ nivesh-app-vm [prod] deploy failed." }
            }
        }

        // ── 4b. Deploy nidp-stack-vm [PROD] ──────────────────────────────────
        // git fetch + reset on the VM — never rsync. Same pattern as the app VM.
        stage('Deploy → nidp-stack-vm [prod]') {
            when {
                expression { env.CURRENT_BRANCH == 'main' && env.DEPLOY_NIDP == 'true' }
            }
            steps {
                withCredentials([sshUserPrivateKey(
                    credentialsId: 'nidp-stack-vm-ssh',
                    keyFileVariable: 'SSH_KEY'
                )]) {
                    sh """
                        ssh -i \$SSH_KEY -o StrictHostKeyChecking=no \\
                            ${env.SSH_USER}@${env.NIDP_VM_HOST} bash <<'REMOTE'
                                set -euo pipefail
                                git -C /opt/nidp/repo fetch --quiet origin main
                                git -C /opt/nidp/repo reset --hard --quiet origin/main
                                sudo systemctl reload cron 2>/dev/null || true
                                sudo systemctl is-active --quiet nidp-query-api && sudo systemctl restart nidp-query-api || true
                                sudo systemctl is-active --quiet nidp-daas && sudo systemctl restart nidp-daas || true
                                echo "NIDP prod services reloaded."
REMOTE
                    """
                }
            }
            post {
                success { echo "✅ nidp-stack-vm [prod] deploy complete." }
                failure { echo "❌ nidp-stack-vm [prod] deploy failed." }
            }
        }

        // ── 5. Health checks ─────────────────────────────────────────────────
        // Staging deploys are handled by GitHub Actions (deploy-*-staging.yml).
        // Jenkins only runs CI + prod deploys so the two systems don't race.
        stage('Health Check [prod]') {
            when {
                expression { env.CURRENT_BRANCH == 'main' }
            }
            parallel {

                stage('App health [prod]') {
                    when {
                        expression { env.CURRENT_BRANCH == 'main' && env.DEPLOY_APP == 'true' }
                    }
                    steps {
                        sh '''
                            sleep 15
                            HTTP=$(curl -sf -o /dev/null -w "%{http_code}" \
                                --max-time 10 https://niveshcopilot.com/api/health || echo "000")
                            echo "App [prod] health → HTTP $HTTP"
                            [ "$HTTP" = "200" ] || echo "WARNING: health check returned $HTTP"
                        '''
                    }
                }

                stage('NIDP health [prod]') {
                    when {
                        expression { env.CURRENT_BRANCH == 'main' && env.DEPLOY_NIDP == 'true' }
                    }
                    steps {
                        sh """
                            sleep 8
                            HTTP=\$(curl -sf -o /dev/null -w "%{http_code}" \\
                                --max-time 10 "http://${env.NIDP_VM_HOST}:8010/health" || echo "000")
                            echo "NIDP [prod] health → HTTP \$HTTP"
                            [ "\$HTTP" = "200" ] || echo "WARNING: NIDP prod health returned \$HTTP"
                        """
                    }
                }
            }
        }
    }

    post {
        always {
            echo "Pipeline finished: ${currentBuild.currentResult} [branch: ${env.CURRENT_BRANCH ?: 'unknown'}]"
        }
        failure {
            echo "❌ Build/deploy failed. Check logs above."
            // Add Slack/email notification here if needed:
            // slackSend(channel: '#deploys', message: "Deploy failed on ${env.CURRENT_BRANCH}: ${env.JOB_NAME} ${env.BUILD_URL}")
        }
    }
}
