import json

from cvss.cvss3 import CVSS3
from dojo.models import Finding


class SnykParser(object):

    def get_scan_types(self):
        return ["Snyk Scan"]

    def get_label_for_scan_types(self, scan_type):
        return scan_type  # no custom label for now

    def get_description_for_scan_types(self, scan_type):
        return "Snyk output file (snyk test --json > snyk.json) can be imported in JSON format."

    def get_findings(self, json_output, test):

        reportTree = self.parse_json(json_output)

        if type(reportTree) is list:
            temp = []
            for moduleTree in reportTree:
                temp += self.process_tree(moduleTree, test)
            return temp
        else:
            return self.process_tree(reportTree, test)

    def process_tree(self, tree, test):
        if tree:
            return [data for data in self.get_items(tree, test)]
        else:
            return []

    def parse_json(self, json_output):
        try:
            data = json_output.read()
            try:
                tree = json.loads(str(data, 'utf-8'))
            except:
                tree = json.loads(data)
        except:
            raise Exception("Invalid format")

        return tree

    def get_items(self, tree, test):
        items = {}
        if 'vulnerabilities' in tree:
            vulnerabilityTree = tree['vulnerabilities']

            for node in vulnerabilityTree:

                item = self.get_item(node, test)
                unique_key = node['title'] + str(node['packageName'] + str(
                    node['version']) + str(node['from']) + str(node['id']))
                items[unique_key] = item

        return list(items.values())

    def get_item(self, vulnerability, test):

        # vulnerable and unaffected versions can be in string format for a single vulnerable version,
        # or an array for multiple versions depending on the language.
        if isinstance(vulnerability['semver']['vulnerable'], list):
            vulnerable_versions = ", ".join(vulnerability['semver']['vulnerable'])
        else:
            vulnerable_versions = vulnerability['semver']['vulnerable']

        # Following the CVSS Scoring per https://nvd.nist.gov/vuln-metrics/cvss
        if 'cvssScore' in vulnerability:
            if vulnerability['cvssScore'] is None:
                severity = vulnerability['severity'].title()
            # If we're dealing with a license finding, there will be no cvssScore
            elif vulnerability['cvssScore'] <= 3.9:
                severity = "Low"
            elif vulnerability['cvssScore'] >= 4.0 and vulnerability['cvssScore'] <= 6.9:
                severity = "Medium"
            elif vulnerability['cvssScore'] >= 7.0 and vulnerability['cvssScore'] <= 8.9:
                severity = "High"
            else:
                severity = "Critical"
        else:
            # Re-assign 'severity' directly
            severity = vulnerability['severity'].title()

        # Construct "file_path" removing versions
        vulnPath = ''
        for index, item in enumerate(vulnerability['from']):
            if index == 0:
                vulnPath += "@".join(item.split("@")[0:-1])
            else:
                vulnPath += " > " + "@".join(item.split("@")[0:-1])

        # create the finding object
        finding = Finding(
            title=vulnerability['from'][0] + ": " + vulnerability['title'],
            test=test,
            severity=severity,
            severity_justification="Issue severity of: **" + severity + "** from a base " +
            "CVSS score of: **" + str(vulnerability.get('cvssScore')) + "**",
            description="## Component Details\n - **Vulnerable Package**: " +
            vulnerability['packageName'] + "\n- **Current Version**: " + str(
                vulnerability['version']) + "\n- **Vulnerable Version(s)**: " +
            vulnerable_versions + "\n- **Vulnerable Path**: " + " > ".join(
                vulnerability['from']) + "\n" + vulnerability['description'],
            mitigation="A fix (if available) will be provided in the description.",
            component_name=vulnerability['packageName'],
            component_version=vulnerability['version'],
            false_p=False,
            duplicate=False,
            out_of_scope=False,
            impact=severity,
            static_finding=True,
            dynamic_finding=False,
            file_path=vulnPath,
            vuln_id_from_tool=vulnerability['id'],
        )

        # CVSSv3 vector
        if vulnerability.get('CVSSv3'):
            finding.cvssv3 = CVSS3(vulnerability['CVSSv3']).clean_vector()

        # manage CVE and CWE with idnitifiers
        cve_references = ''
        cwe_references = ''
        if 'identifiers' in vulnerability:
            if 'CVE' in vulnerability['identifiers']:
                cves = vulnerability['identifiers']['CVE']
                if cves:
                    # Per the current json format, if several CVEs listed, take the first one.
                    finding.cve = cves[0]
                    if len(cves) > 1:
                        cve_references = ', '.join(cves)

            if 'CWE' in vulnerability['identifiers']:
                cwes = vulnerability['identifiers']['CWE']
                if cwes:
                    # Per the current json format, if several CWEs, take the first one.
                    finding.cwe = int(cwes[0].split("-")[1])
                    if len(vulnerability['identifiers']['CVE']) > 1:
                        cwe_references = ', '.join(cwes)
                else:
                    finding.cwe = 1035

        references = ''
        if 'id' in vulnerability:
            references = "**SNYK ID**: https://app.snyk.io/vuln/{}\n\n".format(vulnerability['id'])

        if cve_references or cwe_references:
            references += "Several CVEs or CWEs were reported: \n\n{}\n{}\n".format(
                cve_references, cwe_references)

        # Append vuln references to references section
        for item in vulnerability.get('references', []):
            references += "**" + item['title'] + "**: " + item['url'] + "\n"

        finding.references = references

        finding.description = finding.description.strip()

        # Find remediation string limit indexes
        remediation_index = finding.description.find("## Remediation")
        references_index = finding.description.find("## References")

        # Add the remediation substring to mitigation section
        if (remediation_index != -1) and (references_index != -1):
            finding.mitigation = finding.description[remediation_index:references_index]

        return finding
