#!/usr/bin/python3

import sys
from time import ctime, time
import traceback
import smtplib
from email.mime.text import MIMEText
from collections import defaultdict
from typing import Dict, List, Optional
from intermine.webservice import Service

#### CONSTANTS ####

PROGRAM_START = time()

usage = """
%s: Compare templates between two versions of an InterMine webservice

Usage: 
    %s SERVICE_A [SERVICE_B] [EMAIL_TO] [EMAIL_FROM]

Arguments:
    SERVICE_A        URL of primary InterMine service (e.g. www.flymine.org/query)
    SERVICE_B        URL of secondary service to compare against (optional)
                    If omitted, compares SERVICE_A against itself
    EMAIL_TO        Email address to send results to (optional)
                    If omitted, prints results to stdout
    EMAIL_FROM      Email address to send results from (optional) 
                    If omitted, uses EMAIL_TO as sender

Examples:
    %s www.flymine.org/query beta.flymine.org/beta
    %s www.flymine.org/query beta.flymine.org/beta user@example.com
    %s www.flymine.org/query beta.flymine.org/beta user@example.com sender@example.com
"""

SUBJECT = "Template Comparison Results: {service_a} vs {service_b} - {timestamp}"

BODY = """
Template Comparison Summary
==========================

Run Details:
- Started: {initial_time}
- Completed: {time} 
- Duration: {duration:.2f} seconds
- Service A: {rel_a}
- Service B: {rel_b}

Results:
--------
"""

rfc822_specials = '()<>@,;:\\"[]'

#### ROUTINES ####

def compare_templates(url_a: str, url_b: Optional[str] = None, 
                     send_to: Optional[str] = None, send_from: Optional[str] = None) -> None:
    """
    Main program logic
    
    Args:
        url_a: Primary service URL
        url_b: Secondary service URL to compare against
        send_to: Email address to send results to
        send_from: Email address to send results from
    """

    if url_b is None:
        url_b = url_a
    elif isAddressValid(url_b):
        send_to = url_b
        url_b = url_a

    if send_from is None:
        send_from = send_to
    if send_to is not None:
        if not isAddressValid(send_to) or not isAddressValid(send_from):
            raise Exception("Invalid email addresses: '%s', '%s'" % (send_to, send_from))

    results = fetch_results(url_a, url_b)
    report_results(results, send_to, send_from)

def fetch_results(url_a: str, url_b: str) -> Dict:
    """
    Fetch results from services
    
    Args:
        url_a: Primary service URL
        url_b: Secondary service URL
    
    Returns:
        Dict containing failures and row counts for each service
    """
    try:
        services = [Service(url) for url in [url_a, url_b]]
    except Exception as e:
        raise Exception(f"Invalid service urls: '{url_a}', '{url_b}'\n{str(e)}")

    results = {
        "failures_from": {service.release: {} for service in services},
        "rows_from": {service.release: {} for service in services}
    }

    start = time()

    queried = set()

    for service in services:
        if service.release in queried:
            continue
        else:
            queried.add(service.release)

        for name in service.templates.keys():
            try:
                template = service.get_template(name)
            except Exception as e:
                results["failures_from"][service.release][name] = str(e) + "\nXML:\n" + str(service.templates[name])

            print("Querying %s for results for %s" % (service.release, name))
            try: 
                c = template.count()
                results["rows_from"][service.release][name] = c
            except Exception as e:
                results["failures_from"][service.release][name] = str(e)

    end = time()
    total = end - start
    print(f"Finished fetching results: that took {total // 60} min, {total % 60} secs")
    return results

def report_results(results, send_to, send_from):
    """
    Report results by sending an email and/or printing to stdout
    
    Args:
        results: Dict containing failures and row counts from services
        send_to: Email address to send report to (optional)
        send_from: Email address to send report from (required if send_to provided)
    """

    body = create_message_body(results)
    print(body)
    if send_to is not None:
        print("Sending email to %s" % send_to)
        msg = MIMEText(body)
        params = results["rows_from"].keys()
        if len(params) == 1:
            params.append("itself")
        params.append(ctime(time()))
        msg['Subject'] = SUBJECT % tuple(params)
        msg['From'] = send_from
        msg['To'] = send_to
        smtp = smtplib.SMTP('localhost')
        smtp.sendmail(send_from, [send_to], msg.as_string())
        smtp.quit()


def create_message_body(results: Dict) -> str:
    """
    Analyse the data and present it as a string
    
    Args:
        results: Dict containing failures and row counts from services
    
    Returns:
        String containing the report
    """
    releases = results["rows_from"].keys()
    if len(releases) == 1:
        rel_a = releases[0]
        rel_b = rel_a
    else:
        rel_a, rel_b = releases

    body_params = {
        "rel_a": rel_a,
        "rel_b": rel_b,
        "initial_time": ctime(PROGRAM_START),
        "time": ctime(time()),
        "duration": time() - PROGRAM_START
    }

    body = BODY.format(**body_params)

    body += "\nFAILURES:\n"
    failures_from = results['failures_from']
    for rel, failures in failures_from.items():
        if len(failures):
            body += (rel + "\n").ljust(80, "=")  + "\n"
            for name, reason in failures.items():
                body += "%s: %s\n" % (name, reason)

    successes_from = results["rows_from"]
    template_results = {}
    longest_template_name = 0
    for rel, successes in successes_from.items():
        for name, count in successes.items():
            if name not in template_results:
                template_results[name] = defaultdict(lambda: 0) 
            if len(name) > longest_template_name:
                longest_template_name = len(name)
            template_results[name][rel] = count

    if len(releases) > 1:
        body += "\nBY TEMPLATE:\n"

        fmt = "%-" + str(longest_template_name) + "s | %-6s | %-6s | %s\n" 
        body += fmt % ("NAME", rel_a, rel_b, "CATEGORY")
        body += "".ljust(100, "-") + "\n"

        fmt = "%-" + str(longest_template_name) + "s | %6d | %6d | %s\n" 
        for name, results_by_rel in sorted(template_results.items()):
            values = list(results_by_rel.values())
            diff = abs(values[0] - values[1])
            max_c = max(values)

            category = "SAME" if diff == 0 else (
                "CLOSE" if proportion < 0.1 else
                "DIFFERENT" if proportion < 0.5 else
                "VERY DIFFERENT"
            )

            body += fmt % (name, results_by_rel[rel_a], results_by_rel[rel_b], category)

    body += "\nALL SUCCESSES:\n"
    fmt = "%-" + str(longest_template_name) + "s | %6d\n"
    for rel, successes in successes_from.items():
        body += "\n" + (rel + "\n").ljust(80, "=")  + "\n"
        for name, count in sorted(successes.items()):
            body += fmt % (name, count)

    return body

def isAddressValid(addr):
    """
    Check that Email addresses are valid
    
    Args:
        addr: Email address to check
    
    Returns:
        Boolean indicating validity
    """
    # First we validate the name portion (name@domain)
    c = 0
    while c < len(addr):
        if addr[c] == '"' and (not c or addr[c - 1] == '.' or addr[c - 1] == '"'):
            c = c + 1
            while c < len(addr):
                if addr[c] == '"': break
                if addr[c] == '\\' and addr[c + 1] == ' ':
                    c = c + 2
                    continue
                if ord(addr[c]) < 32 or ord(addr[c]) >= 127: return 0
                c = c + 1
            else: return 0
            if addr[c] == '@': break
            if addr[c] != '.': return 0
            c = c + 1
            continue
        if addr[c] == '@': break
        if ord(addr[c]) <= 32 or ord(addr[c]) >= 127: return 0
        if addr[c] in rfc822_specials: return 0
        c = c + 1
    if not c or addr[c - 1] == '.': return 0

    # Next we validate the domain portion (name@domain)
    domain = c = c + 1
    if domain >= len(addr): return 0
    count = 0
    while c < len(addr):
        if addr[c] == '.':
            if c == domain or addr[c - 1] == '.': return 0
            count = count + 1
        if ord(addr[c]) <= 32 or ord(addr[c]) >= 127: return 0
        if addr[c] in rfc822_specials: return 0
        c = c + 1

    return count >= 1


if __name__ == "__main__":
    try:
        compare_templates(*sys.argv[1:])
    except Exception:
        print(traceback.format_exc())
        print(usage % (sys.argv[0], sys.argv[0]))
        sys.exit(1)

