*This tool and the Readme have been generated using an LLM.*

# NGCSIM - NGSpice Corner Simulation Tool

A Python tool for running automated corner simulations on ngspice netlists.

## Features

- **Parameter Variations**: Vary any circuit parameters (voltage, resistance, capacitance, etc.)
- **Temperature Corners**: Simulate across multiple temperature points
- **Library Corners**: Automatically substitute process corner libraries (tt, ff, ss, sf, fs)
- **Multi-Library Support**: Handle multiple libraries with different corner sets
- **Parallel Execution**: Speed up simulations by running multiple corners in parallel
- **CSV Output**: Organized results with corner identification for easy analysis
- **Netlist Preservation**: Optionally keep generated netlists for debugging

## Installation

### Requirements
- Python 3.6 or higher
- ngspice (must be accessible in system PATH)

### Setup
```bash
# Make the script executable
chmod +x ngcsim.py

# Optionally, move to a location in your PATH
sudo cp ngcsim.py /usr/local/bin/ngcsim
```

## Quick Start

1. Add corner configuration commands to your netlist as comments:

```spice
* My Circuit
** ngc_param vdd_p 2.7 3.0 3.3
** ngc_lib technology.lib(typical) tt ff ss
** ngc_temp -40 27 125
** ngc_out delay power

.lib /path/to/technology.lib typical
.param vdd_p=3.0
...
```

2. Run the simulation:

```bash
ngcsim my_circuit.sp
```

3. Results are saved to `my_circuit_corners.csv`

## Configuration Commands

### ngc_param - Parameter Variation
Define parameters to sweep across corners.

**Syntax:**
```spice
** ngc_param <param_name> <value1> <value2> ... <valueN>
```

**Examples:**
```spice
** ngc_param vdd_p 2.7 3.0 3.3
** ngc_param load_cap 1p 5p 10p
** ngc_param timing_delay 1n 5n 10n
```

The parameter names must match `.param` statements in your netlist.

### ngc_lib - Library Corner Variation
Define library corner substitutions.

**Syntax:**
```spice
** ngc_lib <library_file>[(<key>)] <corner1> <corner2> ... <cornerN>
```

**Examples:**
```spice
* Simple library corners (no key)
** ngc_lib process.lib tt ff ss

* With sublibrary key
** ngc_lib models.lib(mos_typ) tt ff ss
** ngc_lib models.lib(res_typ) res_nom res_fast res_slow

* Multiple libraries
** ngc_lib transistors.ngspice(typical) tt ff ss
** ngc_lib resistors.ngspice(nominal) fast slow
```

The tool finds `.lib` statements matching the library file and optional key, then replaces the key with each corner name. Whitespace around the key is ignored.

### ngc_temp - Temperature Variation
Define temperature corners.

**Syntax:**
```spice
** ngc_temp <temp1> <temp2> ... <tempN>
```

**Examples:**
```spice
** ngc_temp -40 27 125
** ngc_temp 0 25 50 75 100
```

Temperatures are in Celsius.

### ngc_out - Output Measures
Define which measurements to extract from simulation results.

**Syntax:**
```spice
** ngc_out <measure1> <measure2> ... <measureN>
```

**Examples:**
```spice
** ngc_out delay_rise delay_fall
** ngc_out power_avg power_peak frequency
```

These names must match `.measure` statements in your netlist.

## Command Line Options

```
usage: ngcsim [-h] [-k] [-j N] [-o FILE] netlist

positional arguments:
  netlist               Input netlist file

optional arguments:
  -h, --help            Show help message and exit
  -k, --keep-netlists   Keep generated corner netlists in /tmp folder
  -j N, --parallel N    Run N simulations in parallel (default: 1)
  -o FILE, --output FILE
                        Output CSV file (default: <netlist>_corners.csv)
```

### Examples

**Basic usage:**
```bash
ngcsim circuit.sp
```

**Parallel execution with 8 jobs:**
```bash
ngcsim -j 8 circuit.sp
```

**Keep netlists for debugging:**
```bash
ngcsim -k circuit.sp
```

**Custom output file:**
```bash
ngcsim -o my_results.csv circuit.sp
```

**Combine options:**
```bash
ngcsim -k -j 4 -o results.csv circuit.sp
```

## Output Format

Results are saved to a CSV file with the following columns:

- `corner_id`: Unique corner identifier (c0001, c0002, ...)
- `temperature`: Temperature in Celsius
- `param_<n>`: Value for each varied parameter
- `lib_<libfile>`: Corner for each library
- `<measure1>`, `<measure2>`, ...: Measured values

When using `--keep-netlists`, corner netlists are saved with filenames matching their corner_id (e.g., c0001.sp, c0002.sp, etc.).

Example output:
```csv
corner_id,temperature,param_vdd_p,lib_technology.lib_mos_typ,rise_time,fall_time
c0001,-40,2.7,tt,1.234e-09,2.345e-09
c0002,-40,2.7,ff,0.987e-09,1.876e-09
c0003,-40,2.7,ss,1.567e-09,2.789e-09
...
```

## Complete Example

**Netlist (inverter.sp):**
```spice
* CMOS Inverter Corner Simulation
** ngc_param vdd_p 2.7 3.0 3.3
** ngc_param load_cap 1p 10p
** ngc_lib ptm45.lib(nmos_typ) tt ff ss
** ngc_lib ptm45.lib(pmos_typ) tt ff ss
** ngc_temp -40 27 125
** ngc_out tphl tplh power

.lib /models/ptm45.lib nmos_typ
.lib /models/ptm45.lib pmos_typ

.param vdd_p=3.0
.param load_cap=1p

Vdd vdd 0 {vdd_p}
Vin in 0 pulse(0 {vdd_p} 0 100p 100p 5n 10n)

Mn out in 0 0 nmos w=1u l=45n
Mp out in vdd vdd pmos w=2u l=45n
Cl out 0 {load_cap}

.measure tran tphl TRIG v(in) VAL={vdd_p/2} FALL=1 TARG v(out) VAL={vdd_p/2} FALL=1
.measure tran tplh TRIG v(in) VAL={vdd_p/2} RISE=1 TARG v(out) VAL={vdd_p/2} RISE=1
.measure tran power AVG power FROM=0 TO=100n

.tran 10p 100n
.end
```

**Run simulation:**
```bash
ngcsim -j 4 -o inverter_results.csv inverter.sp
```

This will simulate:
- 3 supply voltages (2.7V, 3.0V, 3.3V)
- 2 load capacitances (1pF, 10pF)
- 9 corner combinations for NMOS/PMOS (tt/tt, tt/ff, tt/ss, ff/tt, ff/ff, ff/ss, ss/tt, ss/ff, ss/ss)
- 3 temperatures (-40°C, 27°C, 125°C)

Total: 3 × 2 × 9 × 3 = 162 corners

Results will be in `inverter_results.csv`.

## Tips and Best Practices

1. **Start Small**: Test with a few corners first before running hundreds of simulations
2. **Use Parallel Execution**: The `-j` option can significantly speed up large corner sweeps
3. **Keep Netlists for Debugging**: Use `-k` when developing to inspect generated netlists
4. **Organize Outputs**: Use descriptive output filenames for different experiments
5. **Check Measurements**: Ensure your `.measure` statements work correctly in a single simulation first
6. **Library Paths**: Keep library paths absolute or relative to where you run ngcsim

## Troubleshooting

**"ngspice: command not found"**
- Install ngspice and ensure it's in your PATH

**"Warning: ngc_param requires name and at least one value"**
- Check your ngc_param syntax in the netlist

**Measurements show "N/A"**
- Verify your .measure statements work in a manual ngspice run
- Check that measure names in ngc_out match your .measure statements exactly

**Simulations timing out**
- Reduce parallel jobs if system is overloaded
- Check netlist for simulation issues
- Adjust timeout in the script if needed (currently 300 seconds)

## License

Free to use and modify.

## Version

ngcsim v1.0
