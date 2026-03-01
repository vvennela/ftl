def apply_guardrail(guardrail_id, guardrail_version, text):
    """Apply a Bedrock Guardrail to arbitrary text.

    Returns (blocked: bool, findings: list[str]). Never raises.
    """
    if not guardrail_id or not text:
        return False, []
    try:
        import boto3
        client = boto3.client("bedrock-runtime")
        response = client.apply_guardrail(
            guardrailIdentifier=guardrail_id,
            guardrailVersion=guardrail_version or "DRAFT",
            source="OUTPUT",
            content=[{"text": {"text": text}}],
        )
        blocked = response.get("action") == "GUARDRAIL_INTERVENED"
        findings = []
        for assessment in response.get("assessments", []):
            sip = assessment.get("sensitiveInformationPolicy", {})
            for entity in sip.get("piiEntities", []):
                if entity.get("action") in ("BLOCKED", "ANONYMIZED"):
                    findings.append(f"Sensitive info: {entity['type']}")
            for regex in sip.get("regexes", []):
                if regex.get("action") in ("BLOCKED", "ANONYMIZED"):
                    findings.append(f"Pattern match: {regex.get('name', 'custom')}")
            for f in assessment.get("contentPolicy", {}).get("filters", []):
                if f.get("action") == "BLOCKED":
                    findings.append(f"Content policy: {f['type']}")
        return blocked, findings
    except Exception:
        return False, []
