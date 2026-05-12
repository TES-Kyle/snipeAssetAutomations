from utilities.windmill import run_windmill_job

def run_jamf_battery_sync():
    run_windmill_job("https://app.windmill.dev/api/w/trinity-it-dept-test-space/jobs/run/f/u/john/sync_battery_data_from_jamf_to_snipe_it")
