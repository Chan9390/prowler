# Compliance
Prowler allows you to execute checks based on requirements defined in compliance frameworks. By default, it will execute and give you an overview of the status of each compliance framework:

<img src="../img/compliance/compliance.png"/>

> You can find CSVs containing detailed compliance results inside the compliance folder within Prowler's output folder.

## Execute Prowler based on Compliance Frameworks
Prowler can analyze your environment based on a specific compliance framework and get more details, to do it, you can use option `--compliance`:
```sh
prowler <provider> --compliance <compliance_framework>
```
Standard results will be shown and additionally the framework information as the sample below for CIS AWS 2.0. For details a CSV file has been generated as well.

<img src="../img/compliance/compliance-cis-sample1.png"/>

???+ note
    **If Prowler can't find a resource related with a check from a compliance requirement, this requirement won't appear on the output**

## List Available Compliance Frameworks
In order to see which compliance frameworks are cover by Prowler, you can use option `--list-compliance`:
```sh
prowler <provider> --list-compliance
```

The full and updated list of supported compliance frameworks for each provider is available at [Prowler Hub](https://hub.prowler.com/compliance).

## List Requirements of Compliance Frameworks
For each compliance framework, you can use option `--list-compliance-requirements` to list its requirements:
```sh
prowler <provider> --list-compliance-requirements <compliance_framework(s)>
```

Example for the first requirements of CIS 1.5 for AWS:
```
Listing CIS 1.5 AWS Compliance Requirements:

Requirement Id: 1.1
	- Description: Maintain current contact details
	- Checks:
 		account_maintain_current_contact_details

Requirement Id: 1.2
	- Description: Ensure security contact information is registered
	- Checks:
 		account_security_contact_information_is_registered

Requirement Id: 1.3
	- Description: Ensure security questions are registered in the AWS account
	- Checks:
 		account_security_questions_are_registered_in_the_aws_account

Requirement Id: 1.4
	- Description: Ensure no 'root' user account access key exists
	- Checks:
 		iam_no_root_access_key

Requirement Id: 1.5
	- Description: Ensure MFA is enabled for the 'root' user account
	- Checks:
 		iam_root_mfa_enabled

[redacted]

```

## Create and contribute adding other Security Frameworks

This information is part of the Developer Guide and can be found here: https://docs.prowler.cloud/en/latest/tutorials/developer-guide/.
