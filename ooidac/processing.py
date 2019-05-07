
import os
import logging
from copy import deepcopy
import gsw
import ooidac.gps as gps
import numpy as np
from ooidac.data_classes import DbaData
from ooidac.readers.slocum import parse_dba_header
from ooidac.utilities import fwd_fill
from ooidac.ctd import calculate_practical_salinity, calculate_density
from ooidac.constants import (
    SLOCUM_TIMESTAMP_SENSORS,
    SLOCUM_PRESSURE_SENSORS,
    SLOCUM_DEPTH_SENSORS)

logger = logging.getLogger(os.path.basename(__name__))


def create_llat_sensors(
        dba, timesensor=None, pressuresensor=None,
        depthsensor=None, z_from_p=True):

    # List of available dba sensors
    dba_sensors = dba.sensor_names

    # Select the time sensor
    time_sensor = select_time_sensor(dba, timesensor=timesensor)
    if not time_sensor:
        return
    # Select the pressure sensor
    pressure_sensor = select_pressure_sensor(dba, pressuresensor=pressuresensor)
    # Select the depth sensor
    depth_sensor = select_depth_sensor(dba, depthsensor=depthsensor)
    # We must have either a pressure_sensor or depth_sensor to continue
    if not pressure_sensor and not depth_sensor:
        logger.warning(
            'No pressure sensor and no depth sensor found: {:s}'.format(
                dba.source_file)
        )
        return

    # Must have m_gps_lat and m_gps_lon to convert to decimal degrees
    if 'm_gps_lat' not in dba_sensors or 'm_gps_lon' not in dba_sensors:
        logger.warning(
            'Missing m_gps_lat and/or m_gps_lon: {:s}'.format(dba.source_file)
        )
        return

    # Convert m_gps_lat to decimal degrees and create the new sensor
    # definition
    lat_sensor = deepcopy(dba['m_gps_lat'])
    lat_sensor['sensor_name'] = 'llat_latitude'
    lat_sensor['attrs']['source_sensor'] = u'm_gps_lat'
    lat_sensor['attrs']['comment'] = (
            u'm_gps_lat converted to decimal degrees and interpolated'
    )
    # Skip default values (69696969)
    # ToDo: fix this so it doesn't print a warning
    lat_sensor['data'][lat_sensor['data'] > 9000.0] = np.nan
    lat_sensor['data'] = gps.iso2deg(lat_sensor['data'])

    # Convert m_gps_lon to decimal degrees and create the new sensor
    # definition
    lon_sensor = deepcopy(dba['m_gps_lon'])
    lon_sensor['sensor_name'] = 'llat_longitude'
    lon_sensor['attrs']['source_sensor'] = u'm_gps_lon'
    lon_sensor['attrs']['comment'] = (
        u'm_gps_lon converted to decimal degrees and interpolated'
    )
    # Skip default values (69696969)
    # ToDo: fix this so it doesn't print a warning
    lon_sensor['data'][lon_sensor['data'] > 18000] = np.nan
    lon_sensor['data'] = gps.iso2deg(lon_sensor['data'])

    # Interpolate llat_latitude and llat_longitude
    lat_sensor['data'], lon_sensor['data'] = gps.interpolate_gps(
        time_sensor['data'], lat_sensor['data'], lon_sensor['data']
    )

    # If no depth_sensor was selected, use llat_latitude, llat_longitude
    # and llat_pressure to calculate
    if not depth_sensor or z_from_p:
        if pressure_sensor:
            logger.debug(
                'Calculating depth from selected pressure sensor: {:s}'.format(
                    pressure_sensor['attrs']['source_sensor']))

            depth_sensor = {
                'sensor_name': 'llat_depth',
                'attrs': {
                    'source_sensor': 'llat_pressure,llat_latitude',
                    'comment': (
                        u'Calculated from llat_pressure and '
                        u'llat_latitude using gsw.z_from_p'
                    )
                },
                'data': -gsw.z_from_p(
                    pressure_sensor['data'], lat_sensor['data'])
                }
        else:
            logging.warning(
                'No pressure sensor found for calculating depth')

    # Append the llat variables
    dba.add_data(time_sensor)

    if pressure_sensor:
        dba.add_data(pressure_sensor)

    dba.add_data(depth_sensor)

    dba.add_data(lat_sensor)

    dba.add_data(lon_sensor)

    return dba


def select_time_sensor(dba, timesensor=None):
    # Figure out which time sensor to select
    if timesensor:
        if timesensor not in dba.sensor_names:
            logger.warning(
                'Specified timesensor {:s} not found in dba: {:s}, '
                'auto-choosing one instead'.format(
                    timesensor, dba.file_metadata['source_file']))
            timesensor = _autochoose(dba, SLOCUM_TIMESTAMP_SENSORS, 'time')
    else:
        timesensor = _autochoose(dba, SLOCUM_TIMESTAMP_SENSORS, 'time')

    if not timesensor:
        return

    time_sensor = deepcopy(dba[timesensor])
    if not time_sensor:
        return
    time_sensor['sensor_name'] = 'llat_time'
    time_sensor['attrs']['source_sensor'] = timesensor
    time_sensor['attrs']['comment'] = u'Alias for {:s}'.format(timesensor)
    time_sensor['attrs']['units'] = 'seconds since 1970-01-01 00:00:00Z'

    # the new sensor data is the same as the source sensor data, so no ['data']
    # update needed

    return time_sensor


def select_pressure_sensor(dba, pressuresensor=None):
    """Returns selected pressure sensor name and pressure array in decibars"""

    # List of available dba sensors
    dba_sensors = dba.sensor_names

    # User pressuresensor if specified
    if pressuresensor:
        if pressuresensor not in dba_sensors:
            logger.warning(
                'Specified pressuresensor {:s} not found in dba {:s}. '
                'Auto-choosing pressure sensor instead'.format(
                    pressuresensor, dba.file_metadata['source_file']))
            pressuresensor = _autochoose(
                dba, SLOCUM_PRESSURE_SENSORS, 'pressure'
            )
    else:
        pressuresensor = _autochoose(dba, SLOCUM_PRESSURE_SENSORS, 'pressure')

    if not pressuresensor:
        return

    pressure_sensor = deepcopy(dba[pressuresensor])
    if not pressure_sensor:
        return
    pressure_sensor['sensor_name'] = 'llat_pressure'
    pressure_sensor['attrs']['source_sensor'] = pressuresensor
    pressure_sensor['attrs']['comment'] = (
        u'Alias for {:s}, multiplied by 10 to convert from bar to dbar'.format(
            pressuresensor)
    )

    # Convert the pressure sensor from bar to dbar
    pressure_sensor['data'] = pressure_sensor['data'] * 10
    pressure_sensor['attrs']['units'] = 'dbar'

    return pressure_sensor


def select_depth_sensor(dba, depthsensor=None):
    # List of available dba sensors
    dba_sensors = dba.sensor_names

    # User pressuresensor if specified
    if depthsensor:
        if depthsensor not in dba_sensors:
            logger.warning(
                'Specified depthsensor {:s} not found in dba: {:s}, '
                'auto-choosing depth sensor instead'.format(
                    depthsensor, dba.file_metadata['source_file'])
            )
            depthsensor = _autochoose(dba, SLOCUM_DEPTH_SENSORS, 'depth')
    else:
        depthsensor = _autochoose(dba, SLOCUM_DEPTH_SENSORS, 'depth')

    if not depthsensor:
        return

    depth_sensor = deepcopy(dba[depthsensor])
    if not depth_sensor:
        return
    depth_sensor['sensor_name'] = 'llat_depth'
    depth_sensor['attrs']['source_sensor'] = depthsensor
    depth_sensor['attrs']['comment'] = u'Alias for {:s}'.format(depthsensor)

    # the new sensor data is the same as the source sensor data, so no ['data']
    # update needed

    return depth_sensor


def _autochoose(dba, sensorlist, sensortype):
    sensor = None
    for s in sensorlist:
        if s in dba.sensor_names:
            sensor = s
            logger.info('Auto-chose {:s} sensor: {:s}'.format(
                sensortype, sensor)
            )
            break
    if not sensor:
        logger.warning(
            'No {:s} sensor found in dba: {:s}'.format(
                sensortype, dba.file_metadata['source_file'])
        )
    return sensor


def pitch_and_roll(dba, fill='fwd fill'):
    """adds new sensors `pitch` and `roll` to a GliderData instance from
    `m_pitch` and `m_roll` converted to degrees from radians.

    :param dba:  A GliderData or DbaData instance
    :param fill:
    :return: dba:  The same GliderData instance with `pitch` and `roll` added
    """
    if fill == 'fwd fill':
        fill_function = fwd_fill
    elif fill == 'interp':
        def fill_function(param):
            filled_param = np.interp(
                dba.ts, dba.ts[np.isfinite(param)], param[np.isfinite(param)])
            return filled_param
    else:
        def fill_function(param):
            return param

    pitch = dba['m_pitch']
    pitch['sensor_name'] = 'pitch'
    pitch['attrs']['units'] = 'degrees'
    pitch['attrs']['comment'] = (
        'm_pitch converted to degrees and forward filled')
    pitch['data'] = fill_function(np.degrees(pitch['data']))

    roll = dba['m_roll']
    roll['sensor_name'] = 'roll'
    roll['attrs']['units'] = 'degrees'
    roll['attrs']['comments'] = (
        'm_roll converted to degrees and forward filled')
    roll['data'] = fwd_fill(np.degrees(roll['data']))

    dba.add_data(pitch)
    dba.add_data(roll)

    return dba


# TODO: Build a sensor defs (or separate attributes classes) that clearly
#  read in the JSON definitions files and can use those rather than a murky
#  singular ncw class.  Then that can be passed to this function.
def ctd_data(dba, ctd_sensors, ncw):
    # before beginning, check that all the proper sensors are there
    for sensor in ctd_sensors:
        if sensor not in dba.sensor_names:
            logging.warning(
                ('Sensor {:s} for processing CTD data not found in '
                 'dba file {:s}').format(sensor, dba.source_file)
            )
            return

    # if that didn't return, get the sensors needed
    pres = dba['llat_pressure']
    lat = dba['llat_latitude']
    lon = dba['llat_longitude']
    temp = dba['sci_water_temp'] or dba['m_water_temp']
    cond = dba['sci_water_cond'] or dba['m_water_cond']

    # make sure none of the variables are completely empty of data
    for var in [pres, lat, lon, temp, cond]:
        if np.all(np.isnan(var['data'])):
            logging.warning(
                'dba file {:s} contains no valid {:s} values'.format(
                    dba.source_file,
                    var['sensor_name'])
            )
            return

    # Calculate mean llat_latitude and mean llat_longitude
    mean_lat = np.nanmean(lat['data'])
    mean_lon = np.nanmean(lon['data'])

    # Calculate practical salinity
    prac_sal = calculate_practical_salinity(
        cond['data'], temp['data'], pres['data'])
    # Add salinity to the dba
    dba['salinity'] = {
        'sensor_name': 'salinity',
        'attrs': ncw.nc_sensor_defs['salinity']['attrs'],
        'data': prac_sal
    }

    # Calculate density
    density = calculate_density(
        temp['data'], pres['data'], prac_sal, mean_lat, mean_lon)
    # Add density to the dba
    dba['density'] = {
        'sensor_name': 'density',
        'attrs': ncw.nc_sensor_defs['density']['attrs'],
        'data': density
    }
    return dba


class CTDprocessingError(Exception):
    pass


def get_u_and_v(dba, check_files=None):
    if (
            dba.file_metadata['filename_extension'] == 'dbd'
            and check_files
            and 'm_final_water_vx' in dba.sensor_names
    ):
        vx, vy = _get_final_uv(dba, check_files)
    else:
        vx, vy = _get_initial_uv(dba)

    return vx, vy


# ToDo: make these return an array instead?


def _get_initial_uv(dba):
    """

    :param dba:
    :return:
    """
    if 'm_initial_water_vx' in dba.sensor_names:
        vx_sensor = 'm_initial_water_vx'
        vy_sensor = 'm_initial_water_vy'
    elif 'm_water_vx' in dba.sensor_names:
        vx_sensor = 'm_water_vx'
        vy_sensor = 'm_water_vy'
    else:
        return None, None
    logger.debug('Attempting to get u & v from {:s}/vy'.format(vx_sensor))
    vx = dba[vx_sensor]
    vy = dba[vy_sensor]
    seg_initial_ii = np.flatnonzero(np.isfinite(vx['data']))
    vx['data'] = vx['data'][seg_initial_ii[-1]]
    vy['data'] = vy['data'][seg_initial_ii[-1]]

    vx.pop('sensor_name')
    vx['nc_var_name'] = 'u'
    vx['attrs']['source_sensor'] = vx_sensor
    vx['attrs']['source_file'] = dba.source_file
    vy.pop('sensor_name')
    vy['nc_var_name'] = 'v'
    vy['attrs']['source_sensor'] = vy_sensor
    vy['attrs']['source_file'] = dba.source_file

    return vx, vy


def _get_final_uv(dba, check_files):
    """return Eastward velocity `u` and Northward velocity `v` from looking
    ahead of the main glider data file into the next 2 data files given in
    the `check_files` list to retrieve `u` and `v` from the
    m_final_water_vx/vy parameter calculated 1 or 2 files/segments later.

    :param dba:
    :param check_files: sorted list of the next 2 sorted data files following
        the file being processed from the script input list.
    :return: u, v; Eastward velocity and Northward velocity in m/s as data
        particle dictionaries with metadata attributes
    """
    # ToDo: fix so that this won't fail if check_files is not

    # m_final_water_vx/vy from the current segment file applies to the
    # previous diving segment.  It is still retrieved from the current file
    # to compare when the parameter is updated in a later file.
    seg_final_vx = dba.getdata('m_final_water_vx')
    seg_final_vy = dba.getdata('m_final_water_vy')
    seg_final_ii = np.isfinite(seg_final_vx)
    seg_final_vx = seg_final_vx[seg_final_ii][-1]
    seg_final_vy = seg_final_vy[seg_final_ii][-1]
    mis_num = int(dba.file_metadata['the8x3_filename'][:4])
    seg_num = int(dba.file_metadata['the8x3_filename'][4:])

    # check that check_files are in the same mission and next 2 segments
    for next_dba_file in check_files:
        logger.debug(
            "Attempting to find final vx & vy in the next data file"
            "\n\t{:s}".format(next_dba_file)
        )
        header = parse_dba_header(next_dba_file)
        nxt_mis_num = int(header['the8x3_filename'][:4])
        nxt_seg_num = int(header['the8x3_filename'][4:])
        if (nxt_mis_num != mis_num or not (
                nxt_seg_num == seg_num + 1
                or nxt_seg_num == seg_num + 2)):
            logger.debug(
                'next data file {:s} is not the same mission or '
                'next 2 segments'.format(next_dba_file)
            )
            continue
        next_dba = DbaData(next_dba_file)
        if next_dba is None:
            continue
        if 'm_final_water_vx' not in next_dba.sensor_names:
            continue

        # get m_final_water_vx/vy from the next file
        vx = next_dba['m_final_water_vx']
        vy = next_dba['m_final_water_vy']
        vx_data = vx['data']
        vy_data = vy['data']
        next_ii = np.isfinite(vx_data)
        vx_data = vx_data[next_ii]
        vy_data = vy_data[next_ii]

        # find where the final_vx/vy value has changed from the original file
        index = np.flatnonzero(vx_data != seg_final_vx)
        if len(index) > 0:
            vx_data = vx_data[index]
            vy_data = vy_data[index]
            # if there are more than one changed values take the first one
            if len(vx_data) > 1:
                vx_data = vx_data[0]
                vy_data = vy_data[0]
            if (vx_data, vy_data) != (seg_final_vx, seg_final_vy):
                vx['data'] = vx_data
                vx.pop('sensor_name')
                vx['nc_var_name'] = 'u'
                vx['attrs']['source_sensor'] = 'm_final_water_vx'
                vx['attrs']['source_file'] = next_dba.source_file
                vy['data'] = vy_data
                vy.pop('sensor_name')
                vy['nc_var_name'] = 'v'
                vy['attrs']['source_sensor'] = 'm_final_water_vy'
                vy['attrs']['source_file'] = next_dba.source_file
                return vx, vy

    # if vx/vy not found here, return from _get_initial_uv
    return _get_initial_uv(dba)


def get_segment_time_and_pos(dba):

    # get mean segment time and nearest in time lat and lon position as
    # coordinates for the depth averaged velocities

    a = dba.ts is None
    b = dba.underwater_indices is None or len(dba.underwater_indices) == 0
    c = 'llat_latitude' not in dba.sensor_names
    d = 'llat_longitude' not in dba.sensor_names
    if a or b or c or d:
        return

    # ToDo: dba.ts has to be m_present_time for this, should I enforce this
    #  earlier, or pair dba.timesensor with it and if it is not dba.ts,
    #  then grab m_present_time, or just grab it here regardless?
    uw_start_time = dba.ts[dba.underwater_indices[0]]
    uw_end_time = dba.ts[dba.underwater_indices[-1]]

    # borrow the sensor `llat_time`s attributes but change the data
    # to be the calculated scalar mean segment time value
    mean_segment_time = np.mean([uw_start_time, uw_end_time])
    segment_time = dba['llat_time']
    segment_time.pop('sensor_name')
    segment_time['data'] = mean_segment_time
    segment_time['nc_var_name'] = "time_uv"

    # borrow the attributes from the `llat_` sensors and replace the 'data with
    # scalar segment lat and lon
    segment_lat = dba['llat_latitude']
    segment_lat.pop('sensor_name')
    segment_lon = dba['llat_longitude']
    segment_lon.pop('sensor_name')
    lat = segment_lat['data']
    lon = segment_lon['data']

    time_diff = np.abs(dba.ts - mean_segment_time)
    closest_time_index = np.flatnonzero(time_diff == np.min(time_diff))
    segment_lat['data'] = lat[closest_time_index]
    segment_lon['data'] = lon[closest_time_index]
    segment_lat['nc_var_name'] = "lat_uv"
    segment_lon['nc_var_name'] = "lon_uv"

    return segment_time, segment_lat, segment_lon


def o2_s_and_p_comp(dba):
    if 'sci_oxy4_oxygen' not in dba.sensor_names:
        logger.warning(
            'Oxygen data not found in data file {:s}'.format(dba.source_file)
        )
        return dba

    oxygen = dba['sci_oxy4_oxygen']
    oxy = oxygen['data'].copy()
    timestamps = dba.getdata('sci_m_present_time')
    sp = dba.getdata('salinity')
    p = dba.getdata('llat_pressure')
    t = dba.getdata('sci_water_temp')

    oxy_ii = np.isfinite(oxy)
    oxy = oxy[oxy_ii]
    oxy_ts = timestamps[oxy_ii]

    sp = np.interp(oxy_ts, timestamps[np.isfinite(sp)], sp[np.isfinite(sp)])
    p = np.interp(oxy_ts, timestamps[np.isfinite(p)], p[np.isfinite(p)])
    t = np.interp(oxy_ts, timestamps[np.isfinite(t)], t[np.isfinite(t)])

    lon = dba.getdata('llat_longitude')[oxy_ii]  # should already be interp'ed
    lat = dba.getdata('llat_latitude')[oxy_ii]

    # density calculation from GSW toolbox
    sa = gsw.SA_from_SP(sp, p, lon, lat)
    ct = gsw.CT_from_t(sa, t, p)
    pdens = gsw.rho(sa, ct, 0.0)  # potential referenced to p=0

    # Convert from volume to mass units:
    do = 1000*oxy/pdens

    # Pressure correction:
    do = (1 + (0.032*p)/1000) * do

    # Salinity correction (Garcia and Gordon, 1992, combined fit):
    s0 = 0
    ts = np.log((298.15-t)/(273.15+t))
    b0 = -6.24097e-3
    b1 = -6.93498e-3
    b2 = -6.90358e-3
    b3 = -4.29155e-3
    c0 = -3.11680e-7
    bts = b0 + b1*ts + b2*ts**2 + b3*ts**3
    do = np.exp((sp-s0)*bts + c0*(sp**2-s0**2)) * do

    oxygen['sensor_name'] = 'oxygen'
    oxygen['data'] = np.full(len(oxy_ii), np.nan)
    oxygen['data'][oxy_ii] = do
    oxygen['attrs']['units'] = "umol kg-1"
    oxygen['attrs']['comment'] = (
        "Oxygen concentration has been compensated for salinity and "
        "pressure, but has not been corrected for the depth offset "
        "due to pitch of the glider and sensor offset from the CTD.")
    dba.add_data(oxygen)

    return dba