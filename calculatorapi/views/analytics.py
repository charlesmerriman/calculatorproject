"""
Staff-only analytics dashboard, served inside the Django admin.

The view itself has no auth logic: it is wrapped with
``admin.site.admin_view()`` in calculatorproject/urls.py, which redirects
anonymous and non-staff users to the admin login and marks responses
never-cache. All numbers come from calculatorapi.analytics — this module
only renders them (HTML page or CSV download).
"""

import csv

from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from calculatorapi.analytics import build_analytics_report


def analytics_dashboard(request):
    """Render the analytics snapshot; ``?format=csv`` downloads it instead."""
    report = build_analytics_report()
    if request.GET.get("format") == "csv":
        return _csv_response(report)
    context = {
        # each_context() supplies the admin chrome (site header, nav
        # sidebar, user tools) so the template renders like a native
        # admin page.
        **admin.site.each_context(request),
        "title": "Analytics",
        "report": report,
    }
    return render(request, "admin/analytics.html", context)


def _csv_response(report):
    """
    Serialize the report into a single sectioned CSV.

    One file (section title row, header row, data rows, blank line) keeps
    the download simple to open in Google Sheets/Excel. The dated filename
    doubles as poor-man's history: keep monthly downloads and trends can be
    charted later even though v1 stores no history server-side.
    """
    today = timezone.localdate().isoformat()
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="analytics-{today}.csv"'
    writer = csv.writer(response)

    writer.writerow(["Uma Calculator Analytics",
                     f"generated {report['generated_at']:%Y-%m-%d %H:%M}"])
    writer.writerow([])

    writer.writerow(["Overview"])
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Total users (non-staff)", report["total_users"]])
    writer.writerow(["Engaged users", report["engaged_users"]])
    writer.writerow(["Engaged %", report["engaged_pct"]])
    writer.writerow([])

    writer.writerow(["Paid Products"])
    writer.writerow(["Product", "Users", "% of total", "% of engaged"])
    for product in report["paid_products"]:
        writer.writerow([product["label"], product["count"],
                         product["pct_of_total"], product["pct_of_engaged"]])
    writer.writerow([])

    for distribution in report["rank_distributions"]:
        writer.writerow([f"Rank Distribution — {distribution['label']}"])
        writer.writerow(["Rank", "Users", "% of total"])
        for row in distribution["rows"]:
            writer.writerow([row["name"], row["count"], row["pct_of_total"]])
        writer.writerow([])

    writer.writerow(["Average Current Resources (engaged users)"])
    writer.writerow(["Resource", "Average"])
    for resource in report["resource_averages"]:
        writer.writerow([resource["label"], resource["avg"]])
    writer.writerow([])

    for title, key in [("Popular Uma Banners", "popular_uma_banners"),
                       ("Popular Support Banners", "popular_support_banners")]:
        writer.writerow([title])
        writer.writerow(["Banner", "Timeline", "Start", "End",
                         "Planners", "Total pulls", "Avg pulls"])
        for banner in report[key]:
            writer.writerow([
                banner["name"], banner["timeline"],
                banner["start_date"].strftime("%Y-%m-%d"),
                banner["end_date"].strftime("%Y-%m-%d"),
                banner["planners"], banner["total_pulls"], banner["avg_pulls"],
            ])
        writer.writerow([])

    return response
