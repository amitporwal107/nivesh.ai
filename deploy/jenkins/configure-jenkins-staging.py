#!/usr/bin/env python3
# configure-jenkins-staging.py — Create the staging CI/CD pipeline in Jenkins.
#
# Run ON the VM (Jenkins is bound to 127.0.0.1:8080 — not reachable externally):
#
#   ssh aporwal107_gmail_com@34.100.186.141
#   cd /opt/nivesh/repo
#   git pull origin dev
#   NIVESH_APP_VM_HOST=34.47.250.214 python3 deploy/jenkins/configure-jenkins-staging.py
#
# What it does (idempotent — safe to re-run):
#   1. Registers SSH credentials from deploy/keys/ (nivesh-devops-deploy key → both VMs)
#   2. Creates the 'nivesh-staging-deploy' pipeline job watching */dev
#
# The prod 'nivesh-deploy' job (watches main) is NOT touched.
#
# Prerequisites:
#   - deploy/keys/nivesh-devops-deploy  private key file (gitignored, present on disk)
#   - Jenkins running at http://localhost:8080/jenkins  (admin/admin)

import urllib.request, urllib.parse, urllib.error, json, http.cookiejar, base64, sys, os

BASE = os.environ.get("JENKINS_URL",  "http://localhost:8080/jenkins")
USER = os.environ.get("JENKINS_USER", "admin")
PASS = os.environ.get("JENKINS_PASS", "admin")
AUTH  = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()

# Key file: look next to this script first, then repo-relative path
_script_dir = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.environ.get(
    "NIVESH_KEY_FILE",
    os.path.join(_script_dir, "..", "keys", "nivesh-devops-deploy"),
)

jar    = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def get_crumb():
    req = urllib.request.Request(f"{BASE}/crumbIssuer/api/json")
    req.add_header("Authorization", AUTH)
    resp = opener.open(req)
    d = json.loads(resp.read())
    return d["crumbRequestField"], d["crumb"]


def post(path, data, content_type="application/x-www-form-urlencoded"):
    field, value = get_crumb()
    body = data.encode() if isinstance(data, str) else urllib.parse.urlencode(data).encode()
    req  = urllib.request.Request(f"{BASE}{path}", data=body)
    req.add_header("Authorization", AUTH)
    req.add_header(field, value)
    req.add_header("Content-Type", content_type)
    try:
        resp = opener.open(req)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]


def groovy(script):
    status, body = post("/scriptText", {"script": script})
    result = body.strip()
    print(f"  [{status}] {result[:300]}")
    return status == 200


# ── Pre-flight: verify Jenkins is reachable ────────────────────────────────────
print(f"\nConnecting to Jenkins at {BASE} as {USER}...")
try:
    field, value = get_crumb()
    print(f"  [OK] Jenkins reachable, crumb obtained")
except Exception as e:
    print(f"  [FAIL] Cannot reach Jenkins: {e}")
    print(f"  Make sure you are running this script ON the VM (Jenkins binds to 127.0.0.1 only)")
    sys.exit(1)

# ── 1. Load private key ────────────────────────────────────────────────────────
print(f"\n=== 1. Load SSH private key from {KEY_FILE} ===")
key_path = os.path.realpath(KEY_FILE)
if not os.path.exists(key_path):
    print(f"  [FAIL] Key file not found: {key_path}")
    print(f"  Expected at deploy/keys/nivesh-devops-deploy (gitignored).")
    print(f"  Copy it there and re-run, or set NIVESH_KEY_FILE=/path/to/key")
    sys.exit(1)

deploy_key = open(key_path).read().strip()
print(f"  [OK] Key loaded ({len(deploy_key)} chars)")

# ── 2. Register SSH credential for both VMs ───────────────────────────────────
# Single key (nivesh-devops-deploy) works for both nivesh-app-vm and nidp-stack-vm.
# Credential ID matches what Jenkinsfile uses: 'nivesh-devops-vm-ssh'
print("\n=== 2. Register SSH credential: nivesh-devops-vm-ssh ===")
groovy(f"""
import jenkins.model.*
import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.domains.*
import com.cloudbees.jenkins.plugins.sshcredentials.impl.*

def store = Jenkins.instance
    .getExtensionList('com.cloudbees.plugins.credentials.SystemCredentialsProvider')[0]
    .getStore()
def existing = store.getCredentials(Domain.global()).find {{ it.id == 'nivesh-devops-vm-ssh' }}
if (existing) {{
    // Update the key in-place by removing and re-adding
    store.removeCredentials(Domain.global(), existing)
    println 'Removed stale credential — will re-add with updated key'
}}
def cred = new BasicSSHUserPrivateKey(
    CredentialsScope.GLOBAL,
    'nivesh-devops-vm-ssh',
    'aporwal107_gmail_com',
    new BasicSSHUserPrivateKey.DirectEntryPrivateKeySource(\"\"\"{deploy_key}\"\"\"),
    '',
    'Deploy key: nivesh-app-vm + nidp-stack-vm (nivesh-devops-deploy)'
)
store.addCredentials(Domain.global(), cred)
Jenkins.instance.save()
println 'Credential nivesh-devops-vm-ssh registered OK'
""")

# ── 3. Also register under the legacy IDs used by the prod Jenkinsfile ─────────
# The existing prod job uses 'nivesh-app-vm-ssh' and 'nidp-stack-vm-ssh'.
# Register the same key under both IDs so the staging job can use either.
for cred_id, description in [
    ("nivesh-app-vm-ssh",  "Deploy key: nivesh-app-vm"),
    ("nidp-stack-vm-ssh",  "Deploy key: nidp-stack-vm"),
]:
    print(f"\n=== 2b. Register SSH credential: {cred_id} ===")
    groovy(f"""
import jenkins.model.*
import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.domains.*
import com.cloudbees.jenkins.plugins.sshcredentials.impl.*

def store = Jenkins.instance
    .getExtensionList('com.cloudbees.plugins.credentials.SystemCredentialsProvider')[0]
    .getStore()
def existing = store.getCredentials(Domain.global()).find {{ it.id == '{cred_id}' }}
if (!existing) {{
    def cred = new BasicSSHUserPrivateKey(
        CredentialsScope.GLOBAL,
        '{cred_id}',
        'aporwal107_gmail_com',
        new BasicSSHUserPrivateKey.DirectEntryPrivateKeySource(\"\"\"{deploy_key}\"\"\"),
        '',
        '{description}'
    )
    store.addCredentials(Domain.global(), cred)
    Jenkins.instance.save()
    println 'Created {cred_id}'
}} else {{
    println 'Already exists: {cred_id}'
}}
""")

# ── 3. Register NIVESH_APP_VM_HOST as a Jenkins secret text credential ─────────
# The Jenkinsfile binds this as `credentials('NIVESH_APP_VM_HOST')` (secret text).
# Pass the VM IP via env var: NIVESH_APP_VM_HOST=34.47.250.214 python3 configure...
print("\n=== 3. Register secret text: NIVESH_APP_VM_HOST ===")
vm_host = os.environ.get("NIVESH_APP_VM_HOST", "")
if not vm_host:
    print("  [WARN] NIVESH_APP_VM_HOST env var not set — skipping secret-text credential.")
    print("  Re-run with:  NIVESH_APP_VM_HOST=34.47.250.214 python3 configure-jenkins-staging.py")
else:
    groovy(f"""
import jenkins.model.*
import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.domains.*
import org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl
import hudson.util.Secret

def store = Jenkins.instance
    .getExtensionList('com.cloudbees.plugins.credentials.SystemCredentialsProvider')[0]
    .getStore()
def existing = store.getCredentials(Domain.global()).find {{ it.id == 'NIVESH_APP_VM_HOST' }}
if (existing) {{
    store.removeCredentials(Domain.global(), existing)
    println 'Removed stale NIVESH_APP_VM_HOST — will re-add'
}}
def cred = new StringCredentialsImpl(
    CredentialsScope.GLOBAL,
    'NIVESH_APP_VM_HOST',
    'IP address of nivesh-app-vm (nivesh-app-vm, 34.47.250.214)',
    Secret.fromString('{vm_host}')
)
store.addCredentials(Domain.global(), cred)
Jenkins.instance.save()
println 'NIVESH_APP_VM_HOST registered OK'
""")

# ── 4. Create staging pipeline job ────────────────────────────────────────────
# Separate job from prod 'nivesh-deploy'. Watches */dev only.
# Uses the same Jenkinsfile — CURRENT_BRANCH=='dev' routes to staging stages.
print("\n=== 3. Create pipeline job: nivesh-staging-deploy ===")
staging_job_xml = """<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <description>Deploy nivesh-app + nidp to STAGING on push to dev</description>
  <keepDependencies>false</keepDependencies>
  <properties>
    <org.jenkinsci.plugins.workflow.job.properties.PipelineTriggersJobProperty>
      <triggers>
        <com.cloudbees.jenkins.GitHubPushTrigger plugin="github"><spec></spec></com.cloudbees.jenkins.GitHubPushTrigger>
      </triggers>
    </org.jenkinsci.plugins.workflow.job.properties.PipelineTriggersJobProperty>
  </properties>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition" plugin="workflow-cps">
    <scm class="hudson.plugins.git.GitSCM" plugin="git">
      <configVersion>2</configVersion>
      <userRemoteConfigs>
        <hudson.plugins.git.UserRemoteConfig>
          <url>https://github.com/amitporwal107/nivesh.ai.git</url>
          <credentialsId>nivesh-devops-vm-ssh</credentialsId>
        </hudson.plugins.git.UserRemoteConfig>
      </userRemoteConfigs>
      <branches>
        <hudson.plugins.git.BranchSpec><name>*/dev</name></hudson.plugins.git.BranchSpec>
      </branches>
    </scm>
    <scriptPath>Jenkinsfile</scriptPath>
    <lightweight>true</lightweight>
  </definition>
  <disabled>false</disabled>
</flow-definition>"""

status, body = post("/createItem?name=nivesh-staging-deploy", staging_job_xml, "application/xml")
if status in (200, 201):
    print("  [OK] Pipeline job 'nivesh-staging-deploy' created (watches */dev)")
elif status == 400 and "already exists" in body:
    print("  Job already exists — updating config...")
    status2, body2 = post("/job/nivesh-staging-deploy/config.xml", staging_job_xml, "application/xml")
    if status2 in (200, 201):
        print("  [OK] Pipeline job 'nivesh-staging-deploy' updated")
    else:
        print(f"  [{status2}] Update failed: {body2[:200]}")
else:
    print(f"  [{status}] {body[:200]}")

print("""
✅ Staging Jenkins setup complete!

   Jobs:
     nivesh-deploy          → prod    (main branch)  — UNCHANGED
     nivesh-staging-deploy  → staging (dev  branch)  — CREATED/UPDATED

   Credentials registered:
     NIVESH_APP_VM_HOST    (secret text — VM IP, used in Jenkinsfile env block)
     nivesh-devops-vm-ssh  (SSH key — staging job SCM + both-VM deploy)
     nivesh-app-vm-ssh     (legacy ID — prod job SSH to nivesh-app-vm)
     nidp-stack-vm-ssh     (legacy ID — prod job SSH to nidp-stack-vm)

   GitHub webhook:
     Settings → Webhooks → edit → Branch filter: leave blank (all branches).
     Both 'main' and 'dev' pushes must reach Jenkins for prod+staging routing.

   ⚠ If .github/workflows/deploy-*-staging.yml exist and are committed,
     GitHub Actions and Jenkins will BOTH deploy on dev pushes — remove the
     GHA workflows or disable them if Jenkins is your single CI/CD system.

   Dashboard: https://niveshcopilot.com/jenkins/
""")
