#!/usr/bin/env python3
"""
Monitor script that reads the trade scanner log every 3 minutes
and reports progress.
"""
import time
import sys
from datetime import datetime

LOG_FILE = 'trade_scanner.log'

def read_last_n_lines(filepath, n=50):
    """Read last N lines from log file."""
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
            return lines[-n:] if len(lines) >= n else lines
    except FileNotFoundError:
        return []
    except Exception as e:
        return [f"Error reading log: {e}"]

def parse_phase_status(lines):
    """Parse log lines to extract phase status."""
    status = {
        'phase0': {'status': 'pending', 'duration': None, 'symbols': None},
        'phase1': {'status': 'pending', 'duration': None, 'regime': None},
        'phase2': {'status': 'pending', 'duration': None, 'candidates': None},
        'phase3': {'status': 'pending', 'duration': None, 'analyzed': None},
        'phase4': {'status': 'pending', 'duration': None, 'deep_analyzed': None},
        'phase5': {'status': 'pending', 'duration': None, 'report': None},
        'phase6': {'status': 'pending', 'duration': None},
    }

    current_phase = None
    last_timestamp = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Extract timestamp
        try:
            parts = line.split(' - ')
            if len(parts) >= 1 and ' - ' in line:
                ts_str = parts[0]
                last_timestamp = ts_str
        except:
            pass

        # Phase start detection
        if 'PHASE 0:' in line or 'Phase 0:' in line:
            status['phase0']['status'] = 'running'
        elif 'PHASE 1:' in line or 'Phase 1:' in line:
            status['phase0']['status'] = 'complete'
            status['phase1']['status'] = 'running'
        elif 'PHASE 2:' in line or 'Phase 2:' in line:
            status['phase1']['status'] = 'complete'
            status['phase2']['status'] = 'running'
        elif 'PHASE 3:' in line or 'Phase 3:' in line:
            status['phase2']['status'] = 'complete'
            status['phase3']['status'] = 'running'
        elif 'PHASE 4:' in line or 'Phase 4:' in line:
            status['phase3']['status'] = 'complete'
            status['phase4']['status'] = 'running'
        elif 'PHASE 5:' in line or 'Phase 5:' in line:
            status['phase4']['status'] = 'complete'
            status['phase5']['status'] = 'running'
        elif 'PHASE 6:' in line or 'Phase 6:' in line:
            status['phase5']['status'] = 'complete'
            status['phase6']['status'] = 'running'

        # Phase completion detection
        if 'Phase 0 complete' in line or 'PHASE 0 Complete' in line:
            status['phase0']['status'] = 'complete'
            if 'in' in line:
                try:
                    dur = line.split('in')[-1].replace('s', '').strip()
                    status['phase0']['duration'] = dur
                except:
                    pass
        elif 'Phase 1 complete' in line.lower() or 'PHASE 1 complete' in line:
            status['phase1']['status'] = 'complete'
        elif 'Phase 2 complete' in line.lower() or 'PHASE 2 complete' in line:
            status['phase2']['status'] = 'complete'
        elif 'Phase 3 complete' in line.lower() or 'PHASE 3 complete' in line:
            status['phase3']['status'] = 'complete'
        elif 'Phase 4 complete' in line.lower() or 'PHASE 4 complete' in line:
            status['phase4']['status'] = 'complete'
        elif 'Phase 5 complete' in line.lower() or 'PHASE 5 complete' in line:
            status['phase5']['status'] = 'complete'
        elif 'Phase 6 complete' in line.lower() or 'PHASE 6 complete' in line:
            status['phase6']['status'] = 'complete'

        # Extract key metrics
        if 'Symbols for screening:' in line:
            try:
                status['phase0']['symbols'] = line.split(':')[-1].strip()
            except:
                pass
        if 'Tier 1 cache entries:' in line:
            try:
                status['phase0']['tier1'] = line.split(':')[-1].strip()
            except:
                pass
        if 'AI Regime:' in line or 'Final Regime:' in line:
            try:
                status['phase1']['regime'] = line.split(':')[-1].strip()
            except:
                pass
        if 'Found' in line and 'candidates' in line and 'Phase 2' in line:
            try:
                status['phase2']['candidates'] = line.split('Found')[1].split('candidates')[0].strip()
            except:
                pass
        if 'Analyzed' in line and 'opportunities' in line and 'Phase 3' in line:
            try:
                status['phase3']['analyzed'] = line.split('Analyzed')[1].split('opportunities')[0].strip()
            except:
                pass
        if 'Deep analyzed' in line and 'Phase 4' in line:
            try:
                status['phase4']['deep_analyzed'] = line.split('Deep analyzed')[1].split('opportunities')[0].strip()
            except:
                pass
        if 'Report generated:' in line:
            try:
                status['phase5']['report'] = line.split(':')[-1].strip()
            except:
                pass
        if 'WORKFLOW COMPLETE' in line:
            status['workflow'] = 'complete'
        if 'failed' in line.lower() and 'Workflow' in line:
            status['workflow'] = 'failed'

        # Data fetching during Phase 2 detection (BUG!)
        if 'Fetching' in line and ('Phase 2' in line or (status['phase2']['status'] == 'running' and ('fetch' in line.lower() or 'Tier' in line))):
            status['bug_detected'] = f"DATA FETCHING DURING PHASE 2: {line.strip()}"

    status['last_timestamp'] = last_timestamp
    return status

def format_status(status):
    """Format status for display."""
    output = []
    output.append("\n" + "=" * 60)
    output.append(f"PROGRESS REPORT - {status.get('last_timestamp', 'N/A')}")
    output.append("=" * 60)

    phase_icons = {
        'pending': '⏳',
        'running': '▶️',
        'complete': '✅',
        'failed': '❌'
    }

    phases = [
        ('phase0', 'Phase 0: Data Prep', ['symbols', 'tier1']),
        ('phase1', 'Phase 1: AI Regime', ['regime']),
        ('phase2', 'Phase 2: Screening', ['candidates']),
        ('phase3', 'Phase 3: AI Scoring', ['analyzed']),
        ('phase4', 'Phase 4: Deep Analysis', ['deep_analyzed']),
        ('phase5', 'Phase 5: Report', ['report']),
        ('phase6', 'Phase 6: Notify', []),
    ]

    for phase_key, phase_name, metrics in phases:
        phase_status = status.get(phase_key, {})
        s = phase_status.get('status', 'pending')
        icon = phase_icons.get(s, '❓')
        output.append(f"{icon} {phase_name}: {s.upper()}")

        for metric in metrics:
            if phase_status.get(metric):
                output.append(f"     {metric}: {phase_status[metric]}")

    workflow = status.get('workflow', 'running')
    if workflow == 'complete':
        output.append("\n✅ WORKFLOW COMPLETE")
    elif workflow == 'failed':
        output.append("\n❌ WORKFLOW FAILED")
    else:
        output.append("\n⏳ WORKFLOW RUNNING...")

    # Bug detection alert
    if status.get('bug_detected'):
        output.append("\n" + "!" * 60)
        output.append(f"🐛 BUG DETECTED: {status['bug_detected']}")
        output.append("!" * 60)

    output.append("=" * 60)
    return '\n'.join(output)

def monitor_loop(interval_minutes=3):
    """Monitor log file at regular intervals."""
    print(f"Starting monitor - checking log every {interval_minutes} minutes")
    print(f"Log file: {LOG_FILE}")
    print(f"Press Ctrl+C to stop")

    last_line_count = 0

    while True:
        try:
            lines = read_last_n_lines(LOG_FILE, n=100)
            if not lines:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Log file not found or empty")
            else:
                status = parse_phase_status(lines)
                print(format_status(status))

                # Show last few log lines
                print("\nRecent log entries:")
                for line in lines[-5:]:
                    print(f"  {line.strip()}")

            # Check for bug condition
            if status.get('bug_detected'):
                print("\n🚨 BUG: Data fetching detected during Phase 2!")
                print("This means Phase 0 didn't fetch enough data OR Phase 2 is not using cached data.")
                print("The process should be killed and investigated.")
                return False  # Signal to stop

        except Exception as e:
            print(f"\nError during monitoring: {e}")

        print(f"\n--- Next check in {interval_minutes} minutes (Ctrl+C to stop) ---\n")
        time.sleep(interval_minutes * 60)

    return True

if __name__ == '__main__':
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    try:
        monitor_loop(interval)
    except KeyboardInterrupt:
        print("\n\nMonitor stopped by user")
