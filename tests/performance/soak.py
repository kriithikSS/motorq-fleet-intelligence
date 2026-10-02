import time
import logging
from locust.env import Environment
from locustfile import TelemetryUser
from locust import events

logging.basicConfig(level=logging.INFO)

def main():
    # Setup environment and runner
    env = Environment(user_classes=[TelemetryUser])
    env.create_local_runner()
    
    # Start web UI (optional, helpful for monitoring)
    env.create_web_ui("127.0.0.1", 8089)
    
    # Start the test
    # Target: 50,000 users with hatch rate of 1,000 users/sec
    # (Running single core here, normally this would run distributed)
    target_users = 1000
    hatch_rate = 50
    duration = 3600 # 1 hour soak test
    
    logging.info(f"Starting soak test: {target_users} users, {duration} seconds...")
    env.runner.start(target_users, spawn_rate=hatch_rate)
    
    # Wait for the soak test duration
    time.sleep(duration)
    
    # Stop and print stats
    env.runner.quit()
    
    # Final assertion - if failure rate > 1%, fail the build
    failures = env.runner.stats.total.num_failures
    requests = env.runner.stats.total.num_requests
    failure_rate = failures / requests if requests > 0 else 1.0
    
    logging.info(f"Soak test completed. Requests: {requests}, Failures: {failures}, Rate: {failure_rate:.4f}")
    
    if failure_rate > 0.01:
        logging.error("Soak test failed due to high failure rate.")
        exit(1)
    else:
        logging.info("Soak test passed successfully.")
        exit(0)

if __name__ == "__main__":
    main()
