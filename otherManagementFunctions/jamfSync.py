from utilities.windmill import run_windmill_job

def run_snipe_to_jamf_sync():
    run_windmill_job("https://app.windmill.dev/api/w/trinity-it-dept-test-space/jobs/run/f/u/john/asset_tag_sync")
