"""Explicit input contracts for transient shock tubes and imposed-T burner flames."""
import math
from .units import to_si


def _amount(value, quantity):
    return to_si(value['value'], value['units'], quantity) if isinstance(value, dict) else float(value)


def profile_settings(experiment, settings):
    settings = dict(settings)
    if experiment.kind == 'profile':
        settings['profile_model'] = 'adiabatic_constant_volume'
        settings['energy'] = 'on'
    if experiment.kind != 'burner_profile':
        return settings
    settings['profile_model'] = 'burner_imposed_temperature'
    try:
        supplied = settings.get('temperature_profile')
        if supplied is not None:
            z = [to_si(v, supplied.get('distance_units', 'm'), 'distance') for v in supplied['distance']]
            temperatures = [to_si(v, supplied.get('temperature_units', 'K'), 'temperature') for v in supplied['temperature']]
            if len(z) != len(temperatures): raise ValueError('Temperature profile coordinate/value lengths differ')
            pairs = list(zip(z, temperatures))
            source = 'explicit dataset configuration'
        else:
            pairs = []
            sources = []
            for group in experiment.groups:
                distance = next((p for p in group.properties if p.name == 'distance'), None)
                temperature = next((p for p in group.properties if p.name == 'temperature'), None)
                if distance and temperature:
                    pairs.extend((to_si(row[distance.id], distance.units, 'distance'),
                                  to_si(row[temperature.id], temperature.units, 'temperature')) for row in group.points)
                    sources.append(f'{group.id}/{distance.id},{temperature.id}')
            source = 'XML ' + '; '.join(sources)
        unique = {}
        for z, value in pairs:
            if not math.isfinite(z) or z < 0 or not math.isfinite(value) or value <= 0:
                raise ValueError('Invalid distance or temperature in imposed profile')
            if z in unique and not math.isclose(unique[z], value, rel_tol=1e-8, abs_tol=1e-8):
                raise ValueError('Conflicting temperatures at the same burner position')
            unique[z] = value
        pairs = sorted(unique.items())
        if len(pairs) < 2 or pairs[0][0] != 0:
            raise ValueError('Imposed temperature profile needs at least two positions and must start at burner z=0; no extrapolation')
        settings['temperature_profile'] = {'distance': [p[0] for p in pairs], 'temperature': [p[1] for p in pairs]}
        settings['temperature_profile_source'] = source
        settings['burner_width'] = _amount(settings.get('burner_width', pairs[-1][0]), 'distance')
        for key, quantity in [('burner_mass_flux', 'mass flux'), ('burner_inlet_velocity', 'velocity')]:
            common = next((p for p in experiment.common_properties if p.name == quantity and p.value is not None), None)
            if key in settings:
                settings[key] = _amount(settings[key], quantity)
                if common and not math.isclose(settings[key], to_si(common.value, common.units, quantity), rel_tol=1e-8):
                    raise ValueError(f'Conflicting XML/config {key}')
            elif common:
                settings[key] = to_si(common.value, common.units, quantity)
        if not any(p.name == 'temperature' and p.value is not None for p in experiment.common_properties):
            physical = dict(settings.get('conditions', {}))
            if 'temperature' not in physical:
                settings.setdefault('condition_source', 'burner inlet T(z=0) from ' + source)
            physical.setdefault('temperature', pairs[0][1])
            settings['conditions'] = physical
    except (ValueError, TypeError, KeyError) as error:
        settings['profile_input_issues'] = [str(error)]
    return settings


def validate_burner_inputs(experiment, settings):
    errors = list(settings.get('profile_input_issues', []))
    profile = settings.get('temperature_profile', {})
    if not profile or errors: return errors or ['Missing imposed burner temperature profile']
    for key in ('burner_mass_flux', 'burner_inlet_velocity'):
        if key in settings and (not isinstance(settings[key], (int, float)) or not math.isfinite(settings[key]) or settings[key] <= 0):
            errors.append(f'Invalid positive {key}')
    count = sum(key in settings for key in ('burner_mass_flux', 'burner_inlet_velocity'))
    if count != 1: errors.append('Provide exactly one burner_mass_flux (kg/m2/s) or burner_inlet_velocity (m/s)')
    width = settings.get('burner_width', 0)
    if not math.isfinite(width) or width <= 0 or width > profile['distance'][-1]:
        errors.append('Burner domain must be positive and covered by imposed temperature measurements; no extrapolation')
    for group in experiment.groups:
        for condition in group.conditions:
            if condition.scan_value > width:
                errors.append(f'{group.id}: measurement outside burner domain')
            inlet_temperature = condition.temperature
            if inlet_temperature is not None and not math.isclose(inlet_temperature, profile['temperature'][0], rel_tol=1e-6):
                errors.append('Inlet temperature conflicts with imposed T(z=0)')
    return list(dict.fromkeys(errors))


def ignition_settings(settings, mechanism):
    """Substitute dT/dt only for an unimplementable definition, never for failed ignition."""
    declared = settings.get('ignition_type', {})
    resolved = dict(settings)
    resolved.pop('ignition_fallback', None)
    reasons = []
    if declared.get('type') not in {'max', 'd/dt max', '1/2 max', 'd/dt max extrapolated'}:
        reasons.append('unsupported or missing literature ignition definition')
    target = declared.get('target', '')
    if target not in {'p', 'P', 'pressure', 'T', 'temperature'} and mechanism.species_map.get(target, target) not in mechanism.species:
        reasons.append(f'ignition target absent from mechanism: {target or "unspecified"}')
    if reasons and settings.get('ignition_fallback', 'temperature_gradient') == 'temperature_gradient':
        return {**resolved, 'ignition_type': {'target': 'temperature', 'type': 'd/dt max'},
                'ignition_substitution': {'original': dict(declared),
                    'effective': {'target': 'temperature', 'type': 'd/dt max'}, 'reason': '; '.join(reasons)}}
    return resolved


def render_profile_controls(data):
    import streamlit as st
    import yaml
    with st.expander('瞬态 / 平焰剖面与点火定义'):
        policy = data.get('solver', {}).get('ignition_fallback', 'temperature_gradient')
        if st.session_state.get('ignition_policy_source') != policy:
            st.session_state['ignition_policy_source'] = policy
            st.session_state['ignition_fallback_enabled'] = policy == 'temperature_gradient'
        enabled = st.checkbox('文献点火定义无法实现时，使用最大 dT/dt 时刻替代', key='ignition_fallback_enabled', persist_state='session')
        st.caption('默认开启。仅在定义未实现或机理缺少指定目标（如 OH*）时替代；原定义、实际定义及原因写入结果和导出。未点火或峰值不在时间窗内仍报告失败，不伪造延迟。')
        if st.button('应用点火定义设置'):
            data.setdefault('solver', {})['ignition_fallback'] = 'temperature_gradient' if enabled else 'none'
            st.session_state['config_text'] = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
            from .ui_feedback import action_success
            action_success('点火定义设置已应用；请重新预检查。' + ('无法实现的定义将使用最大 dT/dt，并保留替代标记。' if enabled else '已关闭温度梯度替代。'))
            st.rerun()
        st.caption('激波管组分时间历程：绝热定容，按 XML 时间点提取。平焰物种剖面：给定 T(z)，需要 z=0 起始温度及全域覆盖、入口质量通量（或入口流速）、P/入口组成和机理输运数据。可从 XML 提供 T(z)，或在完整配置中设置 temperature_profile。')
        st.caption('同一物理工况的时间/轴向曲线共享一次完整求解，所有物种及测量位置从同一解采样。任务数按物理曲线计数，覆盖率按实验测量值计数；容差或网格验证另计。')
