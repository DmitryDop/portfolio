import json, subprocess, sys, time, urllib.request

MCP = "https://mcp.figma.com/mcp"

def entry():
    raw = subprocess.run(
        ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
        capture_output=True, text=True, check=True).stdout
    oauth = json.loads(raw).get("mcpOAuth", {})
    best = None
    for k, v in oauth.items():
        if not k.startswith("plugin:figma:figma"): continue
        if best is None or v.get("expiresAt", 0) > best.get("expiresAt", 0):
            best = v
    if not best: sys.exit("no figma oauth entry")
    return best

def token():
    e = entry()
    if e.get("expiresAt", 0) / 1000 < time.time() + 60:
        sys.exit("token expired at %s (now %s)" % (e.get("expiresAt"), int(time.time()*1000)))
    return e["accessToken"]

def call(method, params, rid=1):
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}).encode()
    req = urllib.request.Request(MCP, data=body, method="POST", headers={
        "Authorization": "Bearer " + token(),
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-Figma-Plugin-Bundle": "figma_prod@2_2_120",
    })
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.status, r.read().decode("utf-8", "replace")

if __name__ == "__main__":
    st, out = call("tools/list", {})
    print("HTTP", st, "bytes", len(out))
    open("/Users/dmitry/portfolio/tmp/figma_tools_raw.txt", "w").write(out)
