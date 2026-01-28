#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════╗
║                              NGCSIM - User Guide                          ║
║                  NGSpice Corner Simulation Tool v1.0                      ║
╚═══════════════════════════════════════════════════════════════════════════╝

OVERVIEW
--------
ngcsim is a tool for automating corner simulations on ngspice netlists. It 
parses special configuration commands embedded as comments in your netlist and 
generates/runs simulations across all combinations of parameters, temperatures,
and library corners.

NETLIST CONFIGURATION COMMANDS
-------------------------------
All configuration commands are embedded in the netlist as comments (lines 
starting with '*' or '**'). They must start with 'ngc_' to be recognized.

1. ngc_param - Define parameter variations
   Syntax: ngc_param <param_name> <value1> <value2> ... <valueN>
   
   Example:
     ** ngc_param vdd_p 2.7 3.0 3.3
     ** ngc_param timing_delay 1n 5n 10n
   
   The parameter names must match .param statements in your netlist.

2. ngc_lib - Define library corner variations
   Syntax: ngc_lib <library_file> [(<key>)] <corner1> <corner2> ... <cornerN>
   
   Examples:
     ** ngc_lib process.lib tt ff ss
     ** ngc_lib models.lib(mos_typ) tt ff ss
     ** ngc_lib models.lib(res_typ) res_nom res_fast res_slow
   
   - <library_file>: Name of the library file (path reused from .lib statement)
   - (<key>): Optional key to match specific .lib statements (e.g., 'mos_typ')
   - <corner1...>: Corner names to substitute in .lib statements
   
   The tool finds '.lib <path>/<library_file> <key>' statements and replaces
   <key> with each corner name. Whitespace is ignored when matching.

3. ngc_temp - Define temperature variations
   Syntax: ngc_temp <temp1> <temp2> ... <tempN>
   
   Example:
     ** ngc_temp -40 27 125
   
   Temperatures are in Celsius. The tool will set the ngspice temperature.

4. ngc_out - Define output measures to extract
   Syntax: ngc_out <measure1> <measure2> ... <measureN>
   
   Example:
     ** ngc_out trise tfall power_avg
   
   These measure names must match .measure statements in your netlist.
   Results are extracted from ngspice output and saved to CSV.

NETLIST EXAMPLE
---------------
* My Circuit Simulation
** ngc_param vdd_p 2.7 3.0 3.3
** ngc_param vss_p 0
** ngc_lib models.lib(mos_typ) tt ff ss
** ngc_temp -40 27 125
** ngc_out delay_rise delay_fall power_total

.lib /path/to/libs/models.lib mos_typ
.param vdd_p=3.0
.param vss_p=0

* Your circuit here
Vdd vdd 0 {vdd_p}
Vss vss 0 {vss_p}

.measure tran delay_rise TRIG v(in) VAL=1.65 RISE=1 TARG v(out) VAL=1.65 RISE=1
.measure tran power_total INTEG i(Vdd)*{vdd_p} FROM=0 TO=100n

.tran 0.1n 100n
.end

COMMAND LINE USAGE
------------------
Basic usage:
  ngcsim <netlist_file>

Options:
  -k, --keep-netlists     Keep generated corner netlists in /tmp folder
  -j N, --parallel N      Run N simulations in parallel (default: 1)
  -o FILE, --output FILE  Output CSV file (default: <netlist>_corners.csv)
  -n, --no-run            Generate netlists only, do not run simulations
  -h, --help              Show help message

Examples:
  # Run corner simulation with default settings
  ngcsim my_circuit.sp
  
  # Keep generated netlists and run 4 simulations in parallel
  ngcsim -k -j 4 my_circuit.sp
  
  # Generate netlists only without running simulations
  ngcsim -k -n my_circuit.sp
  
  # Specify custom output file
  ngcsim -o results.csv my_circuit.sp

OUTPUT
------
Results are saved to a CSV file with columns:
- corner_id: Unique identifier for the corner (e.g., c0001, c0002, ...)
- temperature: Temperature in Celsius
- param_<n>: Value for each parameter
- lib_<libname>: Corner for each library
- <measure1>, <measure2>, ...: Measured values from simulation

The corner_id can be used to identify and re-simulate specific corners.
When using --keep-netlists, the corner netlists are saved with filenames
matching their corner_id (e.g., c0001.sp, c0002.sp)

DEPENDENCIES
------------
- Python 3.6+
- ngspice (must be in system PATH)

AUTHOR & LICENSE
----------------
ngcsim v1.0
Free to use and modify.
"""

import argparse
import csv
import itertools
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class NgcConfig:
    """Stores corner simulation configuration parsed from netlist."""
    
    def __init__(self):
        self.params: Dict[str, List[str]] = {}  # param_name -> [values]
        self.libs: Dict[Tuple[str, Optional[str]], List[str]] = {}  # (libfile, key) -> [corners]
        self.temps: List[str] = []
        self.outputs: List[str] = []


class NetlistParser:
    """Parses ngspice netlists and extracts ngc_ configuration."""
    
    def __init__(self, netlist_path: str):
        self.netlist_path = netlist_path
        self.lines: List[str] = []
        self.config = NgcConfig()
        
    def parse(self) -> Tuple[List[str], NgcConfig]:
        """Parse netlist and return lines and configuration."""
        with open(self.netlist_path, 'r') as f:
            self.lines = f.readlines()
        
        for line in self.lines:
            self._parse_config_line(line)
        
        return self.lines, self.config
    
    def _parse_config_line(self, line: str):
        """Parse a single line for ngc_ configuration commands."""
        stripped = line.strip()
        
        # Check if line is a comment
        if not (stripped.startswith('*') or stripped.startswith('**')):
            return
        
        # Remove comment markers and strip
        content = stripped.lstrip('*').strip()
        
        if not content.startswith('ngc_'):
            return
        
        parts = content.split()
        if len(parts) < 2:
            return
        
        cmd = parts[0]
        args = parts[1:]
        
        if cmd == 'ngc_param':
            if len(args) < 2:
                print(f"Warning: ngc_param requires name and at least one value: {line.strip()}")
                return
            param_name = args[0]
            param_values = args[1:]
            self.config.params[param_name] = param_values
            
        elif cmd == 'ngc_lib':
            if len(args) < 2:
                print(f"Warning: ngc_lib requires library file and at least one corner: {line.strip()}")
                return
            
            lib_spec = args[0]
            corners = args[1:]
            
            # Parse library file and optional key: libfile.ext or libfile.ext(key)
            match = re.match(r'^([^()]+)(?:\(([^)]+)\))?$', lib_spec)
            if match:
                libfile = match.group(1)
                key = match.group(2) if match.group(2) else None
                self.config.libs[(libfile, key)] = corners
            else:
                print(f"Warning: Invalid library specification: {lib_spec}")
                
        elif cmd == 'ngc_temp':
            self.config.temps = args
            
        elif cmd == 'ngc_out':
            self.config.outputs = args


class CornerGenerator:
    """Generates corner netlists from parsed configuration."""
    
    def __init__(self, lines: List[str], config: NgcConfig, base_netlist: str):
        self.lines = lines
        self.config = config
        self.base_netlist = base_netlist
        
    def generate_corners(self) -> List[Dict]:
        """Generate all corner combinations."""
        corners = []
        
        # Build lists for cartesian product
        param_names = sorted(self.config.params.keys())
        param_values_list = [self.config.params[name] for name in param_names]
        
        lib_keys = sorted(self.config.libs.keys())
        lib_values_list = [self.config.libs[key] for key in lib_keys]
        
        temps = self.config.temps if self.config.temps else ['25']
        
        # Generate all combinations
        corner_id = 0
        
        for temp in temps:
            param_combos = itertools.product(*param_values_list) if param_values_list else [()]
            lib_combos = itertools.product(*lib_values_list) if lib_values_list else [()]
            
            for param_combo in param_combos:
                for lib_combo in lib_combos:
                    corner_id += 1
                    corner = {
                        'id': f'c{corner_id:04d}',
                        'temperature': temp,
                        'params': dict(zip(param_names, param_combo)) if param_names else {},
                        'libs': dict(zip(lib_keys, lib_combo)) if lib_keys else {}
                    }
                    corners.append(corner)
        
        return corners
    
    def create_corner_netlist(self, corner: Dict, output_path: str):
        """Create a netlist file for a specific corner."""
        modified_lines = []
        temp_inserted = False
        
        for line in self.lines:
            # Skip ngc_ configuration lines (keep as comments)
            stripped = line.strip()
            if stripped.lstrip('*').strip().startswith('ngc_'):
                modified_lines.append(line)
                continue
            
            modified_line = line
            
            # Replace .param statements
            for param_name, param_value in corner['params'].items():
                pattern = r'^(\s*\.param\s+' + re.escape(param_name) + r'\s*=\s*)([^\s]+)(.*)'
                match = re.match(pattern, modified_line, re.IGNORECASE)
                if match:
                    modified_line = f"{match.group(1)}{param_value}{match.group(3)}\n"
            
            # Replace .lib statements
            for (libfile, key), corner_value in corner['libs'].items():
                pattern = r'^(\s*\.lib\s+)(.*)/' + re.escape(libfile) + r'(\s+)(\S+)(.*)'
                match = re.match(pattern, modified_line, re.IGNORECASE)
                if match:
                    path_part = match.group(2)
                    whitespace = match.group(3)
                    current_key = match.group(4)
                    rest = match.group(5)
                    
                    # Check if key matches (if specified)
                    if key is None or current_key.strip() == key.strip():
                        modified_line = f"{match.group(1)}{path_part}/{libfile}{whitespace}{corner_value}{rest}\n"
            
            # Check if this line has a .temp statement - replace it
            if re.match(r'^\s*\.temp\s', modified_line, re.IGNORECASE):
                modified_line = f".temp {corner['temperature']}\n"
                temp_inserted = True
            
            modified_lines.append(modified_line)
            
            # Insert temperature before first analysis command if not yet inserted
            if not temp_inserted and re.match(r'^\s*\.(tran|ac|dc|op)\s', modified_line, re.IGNORECASE):
                # Insert .temp before the analysis command
                modified_lines[-1] = f".temp {corner['temperature']}\n"
                modified_lines.append(modified_line)
                temp_inserted = True
        
        # If temperature was never inserted, add it before .end
        if not temp_inserted:
            for i in range(len(modified_lines) - 1, -1, -1):
                if re.match(r'^\s*\.end', modified_lines[i], re.IGNORECASE):
                    modified_lines.insert(i, f".temp {corner['temperature']}\n")
                    break
            else:
                # No .end found, append at the end
                modified_lines.append(f".temp {corner['temperature']}\n")
        
        # Write to file
        with open(output_path, 'w') as f:
            f.writelines(modified_lines)


class SimulationRunner:
    """Runs ngspice simulations and extracts results."""
    
    def __init__(self, output_measures: List[str]):
        self.output_measures = output_measures
    
    def run_simulation(self, netlist_path: str, corner: Dict) -> Dict:
        """Run ngspice simulation and extract measurements."""
        try:
            # Run ngspice
            result = subprocess.run(
                ['ngspice', '-b', netlist_path],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            # Parse output for measurements
            measurements = self._extract_measurements(result.stdout)
            
            # Combine corner info with measurements
            output = {
                'corner_id': corner['id'],
                'temperature': corner['temperature'],
                **{f'param_{k}': v for k, v in corner['params'].items()},
                **{f'lib_{lib[0]}{"_"+lib[1] if lib[1] else ""}': v 
                   for lib, v in corner['libs'].items()},
                **measurements
            }
            
            return output
            
        except subprocess.TimeoutExpired:
            print(f"Warning: Simulation timeout for corner {corner['id']}")
            return self._create_error_result(corner, "TIMEOUT")
        except Exception as e:
            print(f"Warning: Simulation error for corner {corner['id']}: {e}")
            return self._create_error_result(corner, "ERROR")
    
    def _extract_measurements(self, output: str) -> Dict[str, str]:
        """Extract measurement values from ngspice output."""
        measurements = {}
        
        for measure in self.output_measures:
            # Pattern: measure_name = value
            pattern = r'^\s*' + re.escape(measure) + r'\s*=\s*(\S+)'
            
            for line in output.split('\n'):
                match = re.match(pattern, line, re.IGNORECASE)
                if match:
                    measurements[measure] = match.group(1)
                    break
            
            if measure not in measurements:
                measurements[measure] = 'N/A'
        
        return measurements
    
    def _create_error_result(self, corner: Dict, error_type: str) -> Dict:
        """Create result dictionary for failed simulation."""
        result = {
            'corner_id': corner['id'],
            'temperature': corner['temperature'],
            **{f'param_{k}': v for k, v in corner['params'].items()},
            **{f'lib_{lib[0]}{"_"+lib[1] if lib[1] else ""}': v 
               for lib, v in corner['libs'].items()},
        }
        
        for measure in self.output_measures:
            result[measure] = error_type
        
        return result


def run_corner_simulation(args: Tuple) -> Dict:
    """Worker function for parallel simulation execution."""
    netlist_path, corner, output_measures = args
    runner = SimulationRunner(output_measures)
    return runner.run_simulation(netlist_path, corner)


def main():
    parser = argparse.ArgumentParser(
        description='ngcsim - NGSpice Corner Simulation Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='For detailed documentation, see comments at the top of this script.'
    )
    
    parser.add_argument('netlist', help='Input netlist file')
    parser.add_argument('-k', '--keep-netlists', action='store_true',
                       help='Keep generated corner netlists in /tmp folder')
    parser.add_argument('-j', '--parallel', type=int, default=1, metavar='N',
                       help='Run N simulations in parallel (default: 1)')
    parser.add_argument('-o', '--output', help='Output CSV file (default: <netlist>_corners.csv)')
    parser.add_argument('-n', '--no-run', action='store_true',
                       help='Generate netlists only, do not run simulations (useful with -k)')
    
    args = parser.parse_args()
    
    # Check if netlist exists
    if not os.path.exists(args.netlist):
        print(f"Error: Netlist file not found: {args.netlist}")
        sys.exit(1)
    
    # Determine output file
    if args.output:
        output_file = args.output
    else:
        base = os.path.splitext(os.path.basename(args.netlist))[0]
        output_file = f"{base}_corners.csv"
    
    print("╔═══════════════════════════════════════════════════════════════════════════╗")
    print("║                    NGCSIM - NGSpice Corner Simulation Tool                ║")
    print("╚═══════════════════════════════════════════════════════════════════════════╝")
    print()
    
    # Parse netlist
    print(f"[1/5] Parsing netlist: {args.netlist}")
    parser_obj = NetlistParser(args.netlist)
    lines, config = parser_obj.parse()
    
    print(f"  - Found {len(config.params)} parameter(s)")
    print(f"  - Found {len(config.libs)} library/libraries")
    print(f"  - Found {len(config.temps) if config.temps else 1} temperature(s)")
    print(f"  - Found {len(config.outputs)} output measure(s)")
    
    if not config.outputs:
        print("  ⚠ Warning: No ngc_out measurements defined - no data will be extracted")
    
    print()
    
    # Generate corners
    print("[2/5] Generating corner combinations...")
    
    if not config.params and not config.libs and not config.temps and not config.outputs:
        print("  ⚠ Warning: No ngc_ configuration found - will run single simulation at 25°C")
    
    generator = CornerGenerator(lines, config, args.netlist)
    corners = generator.generate_corners()
    print(f"  - Total corners to simulate: {len(corners)}")
    print()
    
    # Create temporary directory for netlists
    temp_dir = tempfile.mkdtemp(prefix='ngcsim_')
    print(f"[3/5] Creating corner netlists in: {temp_dir}")
    
    netlist_paths = []
    for corner in corners:
        netlist_path = os.path.join(temp_dir, f"{corner['id']}.sp")
        generator.create_corner_netlist(corner, netlist_path)
        netlist_paths.append(netlist_path)
        corner['netlist_path'] = netlist_path
    
    print(f"  - Created {len(netlist_paths)} netlist(s)")
    print()
    
    # Check if we should skip simulation
    if args.no_run:
        print("[4/5] Skipping simulations (--no-run specified)")
        print()
        print("[5/5] No results to write (simulations not run)")
        print()
        
        if args.keep_netlists:
            print(f"Corner netlists preserved in: {temp_dir}")
        else:
            print("⚠ Warning: --no-run without --keep-netlists will delete generated netlists")
            import shutil
            shutil.rmtree(temp_dir)
            print(f"Temporary netlists removed: {temp_dir}")
        
        print()
        print("╔═══════════════════════════════════════════════════════════════════════════╗")
        print("║                      Netlist Generation Complete!                        ║")
        print("╚═══════════════════════════════════════════════════════════════════════════╝")
        return
    
    # Run simulations
    print(f"[4/5] Running simulations (parallel jobs: {args.parallel})...")
    results = []
    
    if args.parallel > 1:
        # Parallel execution
        with ProcessPoolExecutor(max_workers=args.parallel) as executor:
            sim_args = [(corner['netlist_path'], corner, config.outputs) 
                       for corner in corners]
            futures = [executor.submit(run_corner_simulation, arg) for arg in sim_args]
            
            completed = 0
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                    completed += 1
                    if completed % max(1, len(corners) // 20) == 0:
                        print(f"  - Progress: {completed}/{len(corners)} ({100*completed//len(corners)}%)")
                except Exception as e:
                    print(f"  - Simulation failed: {e}")
    else:
        # Sequential execution
        for i, corner in enumerate(corners):
            runner = SimulationRunner(config.outputs)
            result = runner.run_simulation(corner['netlist_path'], corner)
            results.append(result)
            
            if (i + 1) % max(1, len(corners) // 20) == 0:
                print(f"  - Progress: {i+1}/{len(corners)} ({100*(i+1)//len(corners)}%)")
    
    print(f"  - Completed {len(results)} simulation(s)")
    print()
    
    # Sort results by corner_id
    results.sort(key=lambda x: x['corner_id'])
    
    # Write results to CSV
    print(f"[5/5] Writing results to: {output_file}")
    if results:
        fieldnames = list(results[0].keys())
        
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        
        print(f"  - Wrote {len(results)} corner result(s)")
    else:
        print("  - No results to write")
    
    print()
    
    # Clean up temporary files if not keeping
    if not args.keep_netlists:
        import shutil
        shutil.rmtree(temp_dir)
        print(f"Temporary netlists removed: {temp_dir}")
    else:
        print(f"Corner netlists preserved in: {temp_dir}")
    
    print()
    print("╔═══════════════════════════════════════════════════════════════════════════╗")
    print("║                          Simulation Complete!                             ║")
    print("╚═══════════════════════════════════════════════════════════════════════════╝")


if __name__ == '__main__':
    main()
