import streamlit as st
import requests
import toml
import time
import pandas as pd
import altair as alt
import polyline
import pydeck as pdk
import datetime

base_url = 'https://www.strava.com/api/v3'


def load_config():
    with open('config.toml', 'r', encoding='utf-8') as f:
        return toml.load(f)


def save_config(cfg):
    with open('config.toml', 'w', encoding='utf-8') as f:
        toml.dump(cfg, f)


def refresh_token(cfg):
    token_url = 'https://www.strava.com/oauth/token'
    r = requests.post(token_url, data={
        'client_id': cfg['client_id'],
        'client_secret': cfg['client_secret'],
        'refresh_token': cfg['refresh_token'],
        'grant_type': 'refresh_token'
    })
    r.raise_for_status()
    js = r.json()
    cfg['access_token'] = js['access_token']
    cfg['refresh_token'] = js['refresh_token']
    cfg['expires_at'] = js['expires_at']
    save_config(cfg)
    return cfg


def get_activities(access_token, per_page=30, page=1, after=1767225600):
    url = f'{base_url}/athlete/activities'
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {'per_page': per_page, 'page': page, 'after': after}
    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    return r.json()


def get_activity(activity_id, access_token):
    url = f'{base_url}/activities/{activity_id}'
    headers = {'Authorization': f'Bearer {access_token}'}
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()

def calculate_target_km():
    target_km = 2000
    start_of_year = datetime.datetime(datetime.datetime.now().year, 1, 1)
    end_of_year = datetime.datetime(datetime.datetime.now().year, 12, 31)
    today = datetime.datetime.now()
    days_between = (end_of_year - start_of_year).days
    days_passed = (today - start_of_year).days
    target_today = (target_km / days_between) * days_passed
    return target_today


def main():
    st.set_page_config(page_title='Strava — Last Activity', layout='wide')
    st.title('Strava — Last Activity')

    try:
        cfg = load_config()
    except FileNotFoundError:
        st.error('config.yml not found in workspace root.')
        st.stop()

    if cfg.get('expires_at', 0) < time.time():
        with st.spinner('Refreshing access token...'):
            try:
                cfg = refresh_token(cfg)
                st.success('Token refreshed')
            except Exception as e:
                st.error(f'Token refresh failed: {e}')
                st.stop()

    try:
        activities = get_activities(cfg['access_token'], per_page=30)
        activities_df = pd.DataFrame(activities)
    except Exception as e:
        st.error(f'Failed to fetch activities: {e}')
        st.stop()

    if not activities:
        st.info('No activities found.')
        st.stop()


    running_activities = activities_df[activities_df['type'] == 'Run']
    latest = running_activities.iloc[0]
    activity = get_activity(latest['id'], cfg['access_token'])

    current_target_km = calculate_target_km()

    # Key stats
    distance_year_km = activities_df['distance'].sum() / 1000.0
    distance_km = activity.get('distance', 0) / 1000.0
    moving_min = activity.get('moving_time', 0) / 60.0
    elapsed_min = activity.get('elapsed_time', 0) / 60.0
    avg_pace = activity.get('average_speed')
    avg_kmh = (avg_pace * 3.6) if avg_pace else None
    elev = activity.get('total_elevation_gain', 0)


    running_distance_year_km = running_activities['distance'].sum() / 1000.0

    st.subheader('Year-to-date Running stats')
    col1, col2, col3, col4 = st.columns(4, border=True)
    col1.metric('Distance (km)', f'{running_distance_year_km:.2f}')
    col2.metric('Moving time (min)', f'{running_activities["moving_time"].sum() / 60:.0f}')
    col3.metric('Avg pace (km/h)', f'{(running_activities["average_speed"].mean() * 3.6):.2f}')
    col4.metric('Total Activities', f'{len(running_activities)}')

    st.subheader('Latest Run Summary')
    st.subheader(activity.get('name', 'Activity'))

    col1, col2, col3, col4 = st.columns(4, border=True, gap='xsmall')
    col1.metric('Distance (km)', f'{distance_km:.2f}')
    col2.metric('Moving time (min)', f'{moving_min:.0f}')
    col3.metric('Avg speed (km/h)', f'{avg_kmh:.2f}' if avg_kmh else 'N/A')
    col4.metric('Elevation (m)', f'{elev:.0f}')

    df = pd.DataFrame([
        {'label': 'YTD', 'segment': 'Actual', 'kms': running_distance_year_km},
        {'label': 'YTD', 'segment': 'Target', 'kms': max(0, current_target_km - running_distance_year_km)},
    ])

    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X('kms:Q', stack='zero'),
        y=alt.Y('YTD:N'),
        color=alt.Color('segment:N')
    )

    st.altair_chart(chart, use_container_width=True, height=200)
    # Map / route
    route_poly = activity.get('map', {}).get('polyline')
    if route_poly:
        coords = polyline.decode(route_poly)
        df = pd.DataFrame(coords, columns=['lat', 'lon'])

        st.subheader('Route')
        st.map(df)

        midpoint = [df['lat'].mean(), df['lon'].mean()]
        layer = pdk.Layer(
            'PathLayer',
            data=[{'path': coords}],
            get_path='path',
            get_color='[255, 0, 0]',
            width_scale=6,
            width_min_pixels=2,
        )
        view = pdk.ViewState(latitude=midpoint[0], longitude=midpoint[1], zoom=13)
        st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view))
    else:
        st.info('No GPS route (polyline) available for this activity.')

    with st.expander('Raw activity JSON'):
        st.json(activity)


if __name__ == '__main__':
    main()
