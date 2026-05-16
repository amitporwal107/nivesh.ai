#!/usr/bin/env python3
# configure-jenkins.py — Idempotent Jenkins setup via REST API.
#
# Run from the VM (or any host with access to Jenkins):
#   python3 configure-jenkins.py
#
# What it does:
#   1. Installs required plugins
#   2. Creates SSH credentials for nivesh-app-vm and nidp-stack-vm
#   3. Creates secret text for NIVESH_APP_VM_HOST
#   4. Sets Jenkins public URL
#   5. Creates the nivesh-deploy pipeline job (reads Jenkinsfile from main)
#
# Prerequisites:
#   - Jenkins running at http://localhost:8080/jenkins
#   - Private key files at /tmp/nivesh_key and /tmp/nidp_key
#     (copy from deploy/keys/ on the dev machine)

import urllib.request, urllib.parse, urllib.error, json, http.cookiejar, base64, sys, os

BASE = os.environ.get("JENKINS_URL", "http://localhost:8080/jenkins")
USER = os.environ.get("JENKINS_USER", "nivesh-admin")
PASS = os.environ.get("JENKINS_PASS", "nivesh-admin")
AUTH_HEADER = "Basic " + base64.b64encode(f"{USER}:{PASS}".encode()).decode()

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def get_crumb():
    req = urllib.request.Request(f"{BASE}/crumbIssuer/api/json")
    req.add_header("Authorization", AUTH_HEADER)
    resp = opener.open(req)
    d = json.loads(resp.read())
    return d["crumbRequestField"], d["crumb"]


def post(path, data, content_type="application/x-www-form-urlencoded"):
    field, value = get_crumb()
    body = data.encode() if isinstance(data, str) else urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body)
    req.add_header("Authorization", AUTH_HEADER)
    req.add_header(field, value)
    req.add_header("Content-Type", content_type)
    try:
        resp = opener.open(req)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def groovy(script):
    status, body = post("/scriptText", {"script": script})
    result = body.strip()
    print(f"  [{status}] {result[:300]}")
    return status == 200


# ── 1. Install plugins ─────────────────────────────────────────────────────────
print("\n=== 1. Install plugins ===")
groovy("""
import jenkins.model.*
def pm = Jenkins.instance.pluginManager
def uc = Jenkins.instance.updateCenter
uc.updateAllSites()
["workflow-aggregator","github","ssh-agent","git","pipeline-stage-view",
 "credentials-binding","ssh-credentials"].each { p ->
  if (!pm.getPlugin(p)) { def pi = uc.getPlugin(p); if(pi) pi.deploy(true); println "Installing: $p" }
  else println "OK: $p"
}
Jenkins.instance.save()
println "Plugins done"
""")

# ── 2. SSH credential: nivesh-app-vm ──────────────────────────────────────────
print("\n=== 2. SSH credential: nivesh-app-vm ===")
nivesh_key = open("/tmp/nivesh_key").read().strip()
groovy(f"""
import jenkins.model.*
import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.domains.*
import com.cloudbees.jenkins.plugins.sshcredentials.impl.*
def store = Jenkins.instance.getExtensionList('com.cloudbees.plugins.credentials.SystemCredentialsProvider')[0].getStore()
if (!store.getCredentials(Domain.global()).find {{ it.id == 'nivesh-app-vm-ssh' }}) {{
  def cred = new BasicSSHUserPrivateKey(CredentialsScope.GLOBAL, 'nivesh-app-vm-ssh', 'aporwal107_gmail_com',
    new BasicSSHUserPrivateKey.DirectEntryPrivateKeySource(\"\"\"{nivesh_key}\"\"\"), '', 'Deploy key: nivesh-app-vm')
  store.addCredentials(Domain.global(), cred)
  println 'Created nivesh-app-vm-ssh'
}} else {{ println 'Already exists' }}
Jenkins.instance.save()
""")

# ── 3. SSH credential: nidp-stack-vm ──────────────────────────────────────────
print("\n=== 3. SSH credential: nidp-stack-vm ===")
nidp_key = open("/tmp/nidp_key").read().strip()
groovy(f"""
import jenkins.model.*
import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.domains.*
import com.cloudbees.jenkins.plugins.sshcredentials.impl.*
def store = Jenkins.instance.getExtensionList('com.cloudbees.plugins.credentials.SystemCredentialsProvider')[0].getStore()
if (!store.getCredentials(Domain.global()).find {{ it.id == 'nidp-stack-vm-ssh' }}) {{
  def cred = new BasicSSHUserPrivateKey(CredentialsScope.GLOBAL, 'nidp-stack-vm-ssh', 'ubuntu',
    new BasicSSHUserPrivateKey.DirectEntryPrivateKeySource(\"\"\"{nidp_key}\"\"\"), '', 'Deploy key: nidp-stack-vm')
  store.addCredentials(Domain.global(), cred)
  println 'Created nidp-stack-vm-ssh'
}} else {{ println 'Already exists' }}
Jenkins.instance.save()
""")

# ── 4. Secret text: NIVESH_APP_VM_HOST ────────────────────────────────────────
print("\n=== 4. Secret text: NIVESH_APP_VM_HOST ===")
groovy("""
import jenkins.model.*
import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.domains.*
import org.jenkinsci.plugins.plaincredentials.impl.*
def store = Jenkins.instance.getExtensionList('com.cloudbees.plugins.credentials.SystemCredentialsProvider')[0].getStore()
if (!store.getCredentials(Domain.global()).find { it.id == 'NIVESH_APP_VM_HOST' }) {
  store.addCredentials(Domain.global(), new StringCredentialsImpl(CredentialsScope.GLOBAL,
    'NIVESH_APP_VM_HOST', 'nivesh-app-vm IP', hudson.util.Secret.fromString('34.100.186.141')))
  println 'Created NIVESH_APP_VM_HOST'
} else { println 'Already exists' }
Jenkins.instance.save()
""")

# ── 5. Set Jenkins public URL ──────────────────────────────────────────────────
print("\n=== 5. Set Jenkins URL ===")
groovy("""
import jenkins.model.*
def jlc = JenkinsLocationConfiguration.get()
jlc.setUrl('https://niveshcopilot.com/jenkins/')
jlc.save()
println 'Jenkins URL set to https://niveshcopilot.com/jenkins/'
""")

# ── 6. Create pipeline job ─────────────────────────────────────────────────────
print("\n=== 6. Create pipeline job: nivesh-deploy ===")
job_xml = """<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <description>Deploy nivesh-app + nidp to production on push to main</description>
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
        </hudson.plugins.git.UserRemoteConfig>
      </userRemoteConfigs>
      <branches>
        <hudson.plugins.git.BranchSpec><name>*/main</name></hudson.plugins.git.BranchSpec>
      </branches>
    </scm>
    <scriptPath>Jenkinsfile</scriptPath>
    <lightweight>true</lightweight>
  </definition>
  <disabled>false</disabled>
</flow-definition>"""

status, body = post("/createItem?name=nivesh-deploy", job_xml, "application/xml")
if status in (200, 201):
    print("  [OK] Pipeline job 'nivesh-deploy' created")
elif "already exists" in body:
    print("  [OK] Job already exists")
else:
    print(f"  [{status}] {body[:200]}")

print("\n✅ Jenkins configuration complete!")
print("   Dashboard: https://niveshcopilot.com/jenkins/")
print("   Webhook:   https://niveshcopilot.com/jenkins/github-webhook/")
