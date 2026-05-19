// Jenkinsfile — Nivesh.ai CI/CD pipeline
//
// Runs on every push via GitHub webhook.
// Deploys frontend+backend to nivesh-app-vm and/or NIDP to nidp-stack-vm
// depending on what files changed.
//
// Required Jenkins credentials (Manage Jenkins → Credentials):
//   nivesh-app-vm-ssh  — SSH private key for nivesh-app-vm
//   nidp-stack-vm-ssh  — SSH private key for nidp-stack-vm

pipeline {
    agent any

    environment {
        NIVESH_VM_HOST  = credentials('NIVESH_APP_VM_HOST')   // secret text
        NIDP_VM_HOST    = '34.93.60.254'
        SSH_USER        = 'aporwal107_gmail_com'
        DEPLOY_BRANCH   = 'main'
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

        // ── 1. Determine what changed ─────────────────────────────────────
        stage('Changed Paths') {
            steps {
                script {
                    def changed = sh(
                        script: "git diff --name-only HEAD~1 HEAD 2>/dev/null || git diff --name-only HEAD",
                        returnStdout: true
                    ).trim()

                    env.DEPLOY_APP   = changed.find { it.startsWith('frontend/') || (it.startsWith('backend/') && !it.startsWith('backend/nidp/')) || it.startsWith('deploy/nivesh-app/') } ? 'true' : 'false'
                    env.DEPLOY_NIDP  = changed.find { it.startsWith('backend/nidp/') } ? 'true' : 'false'
                    env.ONLY_FRONTEND = (!changed.find { it.startsWith('backend/') } && changed.find { it.startsWith('frontend/') }) ? 'true' : 'false'
                    env.ONLY_BACKEND  = (changed.find { it.startsWith('backend/') && !it.startsWith('backend/nidp/') } && !changed.find { it.startsWith('frontend/') }) ? 'true' : 'false'

                    echo """
Changed files summary:
  Deploy App  : ${env.DEPLOY_APP}
  Deploy NIDP : ${env.DEPLOY_NIDP}
  Frontend-only: ${env.ONLY_FRONTEND}
  Backend-only : ${env.ONLY_BACKEND}
"""
                }
            }
        }

        // ── 2. CI checks ──────────────────────────────────────────────────
        stage('CI — Backend Syntax') {
            when { expression { env.DEPLOY_APP == 'true' || env.DEPLOY_NIDP == 'true' } }
            steps {
                sh '''
                    python3 -m py_compile backend/server.py
                    find backend -name "*.py" -not -path "*/__pycache__/*" \
                        -exec python3 -m py_compile {} +
                    echo "✅ Python syntax OK"
                '''
            }
        }

        stage('CI — Frontend Build') {
            when { expression { env.DEPLOY_APP == 'true' && env.ONLY_BACKEND != 'true' } }
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

        // ── 3. Deploy nivesh-app-vm ───────────────────────────────────────
        stage('Deploy → nivesh-app-vm') {
            when { expression { env.DEPLOY_APP == 'true' } }
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
                                "sudo BRANCH=${env.DEPLOY_BRANCH} bash /opt/nivesh/deploy/redeploy.sh ${flags}"
                        """
                    }
                }
            }
            post {
                success { echo "✅ nivesh-app-vm deploy complete." }
                failure { echo "❌ nivesh-app-vm deploy failed." }
            }
        }

        // ── 4. Deploy nidp-stack-vm ───────────────────────────────────────
        stage('Deploy → nidp-stack-vm') {
            when { expression { env.DEPLOY_NIDP == 'true' } }
            steps {
                withCredentials([sshUserPrivateKey(
                    credentialsId: 'nidp-stack-vm-ssh',
                    keyFileVariable: 'SSH_KEY'
                )]) {
                    sh """
                        rsync -az --delete \\
                            -e "ssh -i \$SSH_KEY -o StrictHostKeyChecking=no" \\
                            --exclude="__pycache__" --exclude="*.pyc" \\
                            --exclude=".git" --exclude="*.egg-info" \\
                            backend/nidp/ \\
                            ${env.SSH_USER}@${env.NIDP_VM_HOST}:/opt/nidp/repo/backend/nidp/

                        ssh -i \$SSH_KEY -o StrictHostKeyChecking=no \\
                            ${env.SSH_USER}@${env.NIDP_VM_HOST} bash <<'REMOTE'
                                sudo systemctl reload cron 2>/dev/null || true
                                sudo systemctl is-active --quiet nidp-query-api && sudo systemctl restart nidp-query-api || true
                                sudo systemctl is-active --quiet nidp-daas && sudo systemctl restart nidp-daas || true
                                echo "NIDP services reloaded."
REMOTE
                    """
                }
            }
            post {
                success { echo "✅ nidp-stack-vm deploy complete." }
                failure { echo "❌ nidp-stack-vm deploy failed." }
            }
        }

        // ── 5. Health checks ──────────────────────────────────────────────
        stage('Health Check') {
            parallel {
                stage('App health') {
                    when { expression { env.DEPLOY_APP == 'true' } }
                    steps {
                        sh '''
                            sleep 15
                            HTTP=$(curl -sf -o /dev/null -w "%{http_code}" \
                                --max-time 10 https://niveshcopilot.com/api/health || echo "000")
                            echo "App health → HTTP $HTTP"
                            [ "$HTTP" = "200" ] || echo "WARNING: health check returned $HTTP"
                        '''
                    }
                }
                stage('NIDP health') {
                    when { expression { env.DEPLOY_NIDP == 'true' } }
                    steps {
                        sh """
                            sleep 8
                            HTTP=\$(curl -sf -o /dev/null -w "%{http_code}" \\
                                --max-time 10 "http://${env.NIDP_VM_HOST}:8010/health" || echo "000")
                            echo "NIDP health → HTTP \$HTTP"
                        """
                    }
                }
            }
        }
    }

    post {
        always {
            echo "Pipeline finished: ${currentBuild.currentResult}"
        }
        failure {
            echo "❌ Build/deploy failed. Check logs above."
            // Add Slack/email notification here if needed:
            // slackSend(channel: '#deploys', message: "Deploy failed: ${env.JOB_NAME} ${env.BUILD_URL}")
        }
    }
}
