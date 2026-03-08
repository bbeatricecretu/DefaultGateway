// Zone-to-camera folder mapping
export const ZONE_CAMERA_MAP = {
  gate1:         { folder: 'Gate_A',        label: 'Gate A',                   color: '#3b82f6' },
  gate2:         { folder: 'Gate_A',        label: 'Gate A',                   color: '#3b82f6' },
  gate3:         { folder: 'Gate_A',        label: 'Gate A',                   color: '#3b82f6' },
  gate4:         { folder: 'Gate_A',        label: 'Gate A',                   color: '#3b82f6' },
  gate5:         { folder: 'Gate_A',        label: 'Gate A',                   color: '#3b82f6' },
  gate6:         { folder: 'Gate_A',        label: 'Gate A',                   color: '#3b82f6' },
  waiting_left:  { folder: 'Departures',    label: 'Departures',               color: '#22c55e' },
  waiting_right: { folder: 'Departures',    label: 'Departures',               color: '#22c55e' },
  security:      { folder: 'Security',      label: 'Security',                 color: '#ef4444' },
  checkin:       { folder: 'Arrivals_Hall', label: 'Arrivals Hall',            color: '#eab308' },
  baggage:       { folder: 'Arrivals_Hall', label: 'Arrivals Hall',            color: '#06b6d4' },
};

// Counter display config
export const COUNTER_ORDER = ['Arrivals Hall', 'Security', 'Departures', 'Gate A'];
export const COUNTER_DISPLAY = {
  'Arrivals Hall': { name: 'Check-in',      sub: 'Check-in Points C1–C10',    color: '#eab308' },
  'Security':      { name: 'Security',      sub: 'Security Points S1–S4',     color: '#ef4444' },
  'Departures':    { name: 'Waiting Halls', sub: 'Waiting Rooms · Gates 1–6', color: '#22c55e' },
  'Gate A':        { name: 'Gate A',        sub: 'Boarding Gates 1–6',        color: '#3b82f6' },
};

export const CAMERA_DISPLAY_NAMES = {
  'Arrivals Hall': 'Check-in',
  'Security':      'Security',
  'Departures':    'Waiting Halls',
  'Gate A':        'Gate A',
};

// Rich flight schedule data
export const FLIGHT_SCHEDULE = {
  DL789: {
    origin: 'JFK · New York',
    destination: 'LHR · London Heathrow',
    gate: 'A7', aircraft: 'Boeing 767-300ER',
    boardingTime: '14:35', departureTime: '15:05',
    prediction: '⛅ Possible delay due to storm approaching LHR. Alternate routing via CDG under evaluation.',
  },
  UA456: {
    origin: "ORD · Chicago O'Hare",
    destination: 'LOCAL · Arrivals Hall',
    gate: 'B12', aircraft: 'Airbus A320neo',
    boardingTime: '—', departureTime: 'LANDED 13:44',
    prediction: '🌧 Extended immigration queues expected from Midwest corridor bunching. Peak in ~18 min.',
  },
  BA112: {
    origin: 'LGW · London Gatwick',
    destination: 'CDG · Paris CDG',
    gate: 'C3', aircraft: 'Airbus A319',
    boardingTime: '15:10', departureTime: '15:45',
    prediction: '❄ De-icing at CDG may cause 20–35 min hold. Gate closure strictly enforced.',
  },
  EK205: {
    origin: 'DXB · Dubai International',
    destination: 'LOCAL · Gate A',
    gate: 'A3', aircraft: 'Boeing 777-300ER',
    boardingTime: '16:00', departureTime: '16:45',
    prediction: '🌬 Crosswinds at DXB on return leg. Departure may push 30–45 min pending ATC slot.',
  },
  FR9032: {
    origin: 'STN · London Stansted',
    destination: 'BCN · Barcelona',
    gate: 'D9', aircraft: 'Boeing 737 MAX 8',
    boardingTime: '13:55', departureTime: '14:25',
    prediction: '🌩 Thunderstorm over Pyrenees — possible holding pattern or Valencia diversion.',
  },
};

export const FLIGHT_PRED_FALLBACK = [
  '🌦 No significant disruptions forecast. All systems nominal.',
  '✅ Optimal conditions. On-time departure anticipated.',
  '⚡ Minor turbulence advisory along route. No operational impact.',
  '🌤 Light crosswinds at destination — standard approach procedures.',
];
