"""Generate data/ground_coords_seed.json from embedded venue coordinates.

Coordinates are WGS84 stadium locations (not city centers), keyed by Sportmonks
venue id. Run: python scripts/generate_coord_seed.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ground_coords_seed.json"

# fmt: off
# sportmonks_id -> (lat, lon)
COORDS: dict[int, tuple[float, float]] = {
    # --- Australia (98) ---
    1: (-34.9156, 138.5961),    # Adelaide Oval
    2: (-31.9559, 115.8772),    # WACA
    3: (-19.3153, 146.7297),    # Riverway Townsville
    4: (-12.3911, 130.8770),    # TIO Darwin
    5: (-42.8780, 147.3340),    # TCA Hobart
    6: (-33.8917, 151.2247),    # SCG
    7: (-33.8471, 151.0633),    # Stadium Australia
    8: (-38.1579, 144.3614),    # Simonds Geelong
    9: (-31.9505, 115.8895),    # Perth Stadium
    10: (-41.4208, 147.1345),   # North Tas Launceston
    11: (-37.8200, 144.9834),   # MCG
    12: (-35.3180, 149.1340),   # Manuka Oval
    13: (-27.4858, 153.0381),   # Brisbane Cricket Ground / Gabba
    14: (-42.8772, 147.3744),   # Bellerive Oval
    143: (-33.8390, 151.2070),  # North Sydney Oval
    146: (-37.8420, 144.9830),  # Junction Oval
    149: (-33.9670, 151.1020),  # Hurstville Oval
    152: (-33.9170, 151.0330),  # Bankstown Oval
    158: (-33.8550, 151.1550),  # Drummoyne Oval
    167: (-27.4350, 153.0080),  # Allan Border Field
    185: (-33.8430, 150.9480),  # Sydney Showground
    188: (-45.2500, 169.3900),  # Molyneux Park Alexandra
    194: (-27.4858, 153.0381),  # The Gabba
    197: (-37.8165, 144.9475),  # Docklands / Marvel Stadium
    200: (-28.0020, 153.3800),  # Carrara Oval
    215: (-41.4208, 147.1345),  # Aurora Stadium Launceston
    971: (-41.2380, 146.4050),  # Latrobe Recreation Ground Tasmania
    218: (-23.6980, 133.8800),  # Traeger Park Alice Springs
    272: (-34.9156, 138.5961),  # Gliderol Adelaide
    275: (-34.4250, 150.8930),  # North Dalton Park Wollongong
    278: (-16.9180, 145.7480),  # Cazalys Cairns
    296: (-38.1579, 144.3614),  # Geelong Cricket Ground
    302: (-41.0540, 145.9030),  # West Park Oval Burnie
    305: (-37.5620, 143.8580),  # Eastern Oval Ballarat
    308: (-38.1780, 146.2600),  # Ted Summerton Moe
    311: (-38.1150, 145.3000),  # Casey Fields Melbourne
    314: (-34.9156, 138.5961),  # Karen Rolton Adelaide
    317: (-31.9505, 115.8895),  # Lilac Hill Perth
    320: (-33.7710, 150.9060),  # Blacktown Sportspark
    323: (-21.1420, 149.1860),  # Harrup Park Mackay
    332: (-37.8250, 145.0700),  # Camberwell Melbourne
    335: (-36.0740, 146.9140),  # Lavington Albury
    338: (-33.7510, 150.6940),  # Howell Oval Penrith
    341: (-33.7510, 150.6940),  # Howell Oval Penrith (dup)
    344: (-35.1080, 147.3690),  # Robertson Wagga
    507: (-41.4208, 147.1345),  # Invermay Launceston
    510: (-34.4760, 139.0100),  # Nuriootpa
    564: (-12.3911, 130.8770),  # Marrara Darwin 2
    567: (-12.3911, 130.8770),  # Cazalys NT
    570: (-12.3911, 130.8770),  # Marrara Darwin 1
    573: (-12.3911, 130.8770),  # Gardens Oval Darwin
    576: (-12.3911, 130.8770),  # Tracy Village Darwin
    579: (-12.3911, 130.8770),  # Fred's Pass Darwin
    582: (-12.3911, 130.8770),  # Kahlin Oval Darwin
    606: (-12.3911, 130.8770),  # Nightcliff Darwin
    672: (-34.9156, 138.5961),  # Park 25 Adelaide
    737: (-27.4858, 153.0381),  # Ian Healy Kalinga Brisbane
    758: (-34.9156, 138.5961),  # Gerry Wood Adelaide
    761: (-37.8200, 144.9834),  # DXC Arena Melbourne
    785: (-30.2960, 153.1150),  # Coffs Harbour
    1148: (-21.1420, 149.1860), # Great Barrier Reef Arena Mackay
    1217: (-33.8917, 151.2247), # Cricket Central Sydney
    1318: (-28.0020, 153.3800), # Bill Pippen Gold Coast
    1329: (-12.3911, 130.8770), # Cazalys Palmerston

    # --- Bangladesh ---
    15: (22.3560, 91.7830),     # M.A. Rahman Stadium Chittagong
    16: (24.8940, 91.8680),     # Sylhet
    17: (23.8150, 90.3610),     # Shere Bangla Mirpur
    18: (22.8450, 89.5400),     # Sheikh Abu Naser Khulna
    19: (24.8500, 89.3700),     # Bogra
    20: (22.3560, 91.7830),     # MA Aziz Chittagong
    21: (23.6310, 90.5030),     # Khan Shaheb Fatullah
    22: (23.7270, 90.3960),     # Bangabandhu Dhaka
    1160: (23.8150, 90.3610),   # Mirpur Cricket Stadium
    941: (24.8940, 91.8680),    # Sylhet Outer
    1341: (24.3740, 88.6010),   # Rajshahi

    # --- England / UK county ---
    23: (52.9369, -1.1322),     # Trent Bridge
    24: (50.9240, -1.3210),     # Rose Bowl / Ageas
    25: (51.0190, -3.1040),     # Taunton
    26: (52.9140, -1.4580),     # Derby 3aaa
    27: (51.2670, 1.0870),      # St Lawrence Canterbury
    797: (51.2780, 1.0890),     # Polo Farm Canterbury
    800: (53.4300, -2.3200),    # Rookwood Sale Cheshire
    28: (51.6190, -3.9430),     # St Helen's Swansea
    29: (51.4870, -3.1910),     # Sophia Gardens Cardiff
    30: (54.8500, -1.5590),     # Riverside Chester-le-Street
    31: (53.4631, -2.2913),     # Old Trafford
    32: (54.2790, -0.4020),     # North Marine Scarborough
    33: (51.1320, 0.2630),      # Nevill Tunbridge Wells
    34: (51.5294, -0.1727),     # Lord's
    35: (51.4821, -0.1117),     # Kennington Oval
    36: (53.8170, -1.5820),     # Headingley
    37: (52.6240, -1.1330),     # Grace Road Leicester
    38: (52.4560, -1.9030),     # Edgbaston
    39: (50.9240, -1.3210),     # County Ground Southampton
    40: (52.2480, -0.8710),     # Northampton
    41: (52.1890, -2.2230),     # New Road Worcester
    42: (50.8300, -0.1640),     # Hove
    43: (51.7330, 0.4730),      # Chelmsford
    44: (51.4770, -2.6200),     # Bristol
    45: (53.3700, -1.4700),     # Bramall Lane
    221: (52.1890, -2.2230),    # County Ground New Road
    224: (51.5450, -0.4780),    # Uxbridge
    227: (51.6100, -0.4200),    # Merchant Taylors Northwood
    230: (51.4100, 0.0200),     # Kent Beckenham
    233: (51.9000, -2.0800),    # College Cheltenham
    236: (53.2350, -1.4250),    # Queen's Park Chesterfield
    239: (50.8540, -0.5530),    # Arundel Castle
    242: (51.4600, -0.3030),    # Old Deer Park Richmond
    245: (53.3750, -2.9400),    # Aigburth Liverpool
    248: (51.2350, -0.5700),    # Woodbridge Guildford
    251: (53.6220, -3.0150),    # Trafalgar Birkdale
    254: (53.2950, -3.7260),    # Colwyn Bay
    257: (52.7700, -1.2100),    # Haslegrave Loughborough
    260: (53.9600, -1.0870),    # Clifton York
    263: (53.8150, -3.0500),    # Stanley Blackpool
    281: (51.6860, -0.3160),    # Radlett
    284: (55.0060, -1.6200),    # Roseworth Gosforth
    287: (53.1700, -1.0500),    # Welbeck Colliery
    290: (52.6700, -0.7300),    # Oakham
    293: (50.7700, 0.2800),     # Saffrons Eastbourne
    391: (52.9150, -0.6400),    # Gorse Lane Grantham
    414: (53.1000, -1.0500),    # John Fretwell Nettleworth
    423: (53.9600, -1.0870),    # York CC
    426: (52.3850, -2.2500),    # Chester Road Kidderminster
    432: (54.3220, -2.5270),    # Sedbergh
    456: (57.1500, -2.0900),    # Mannofield Aberdeen
    630: (51.6860, -0.3160),    # Brunton Radlett
    743: (51.2670, 1.0870),     # Kent CCC
    770: (52.5400, -0.9900),    # Kibworth
    773: (53.1900, -2.8900),    # Boughton Hall Chester
    776: (52.2050, 0.1150),     # Fenner's Cambridge
    914: (55.8420, -4.2800),    # Titwood Glasgow
    920: (55.4580, -4.6290),    # Cambusdoon Ayr
    926: (51.6620, -3.7900),    # Gnoll Neath
    932: (53.2500, -1.0500),    # Welbeck Abbey
    1082: (51.6600, -0.9200),   # Wormsley
    1094: (51.4000, -1.3200),   # Enborne Newbury
    1097: (50.9240, -1.3210),   # Ageas Bowl
    1100: (54.8500, -1.5590),   # Seat Unique Riverside
    1103: (51.2670, 1.0870),    # Spitfire Canterbury
    1118: (52.4100, -1.7800),   # Moseley Solihull
    1121: (51.1900, -2.7200),   # Millfield
    1124: (55.9600, -3.2100),   # Goldenacre Edinburgh
    1130: (51.4100, 0.0200),    # Foxgrove Beckenham
    1133: (52.4560, -1.9030),   # Edgbaston Foundation
    1223: (56.4600, -3.0500),   # Forthill Dundee
    1240: (50.8300, -0.1640),   # Royal Brunswick Brighton
    1246: (53.8150, -3.0500),   # Whitegate Blackpool
    1252: (53.2300, -0.5400),   # Lindum Lincoln
    1258: (51.4100, 0.0200),    # Kent Beckenham
    1261: (52.3700, -1.2600),   # Rugby School
    1272: (52.4100, -1.7800),   # Old Edwardian Solihull
    1326: (51.2350, -0.5700),   # Guildford Bason
    1327: (52.4560, -1.9030),   # Mitchells Birmingham
    1328: (51.4200, -0.2200),   # Raynes Park
    1332: (51.0190, -3.1040),   # Taunton Vale
    1361: (50.6200, -3.4100),   # Maer Exmouth

    # --- India (major + domestic) ---
    46: (18.9389, 72.8258),     # Wankhede
    47: (21.1520, 79.0880),     # VCA Stadium Nagpur
    48: (21.1450, 79.0880),     # VCA Ground Nagpur
    49: (8.5240, 76.9360),      # University Stadium Trivandrum
    50: (26.8500, 80.9500),     # University Lucknow
    51: (26.9160, 75.7870),     # Sawai Mansingh Jaipur
    52: (22.3030, 70.8020),     # SCA Stadium Rajkot
    53: (22.3080, 73.1810),     # Reliance Vadodara
    54: (17.4065, 78.5505),     # RGICS Hyderabad
    55: (30.6900, 76.7370),     # Mohali IS Bindra
    56: (18.5200, 73.8560),     # Nehru Pune
    57: (18.6740, 73.8060),     # MCA Pune
    58: (13.0627, 80.2792),     # MA Chidambaram Chennai
    59: (12.9788, 77.5996),     # Chinnaswamy Bengaluru
    60: (23.3560, 85.3250),     # JSCA Ranchi
    61: (22.7190, 75.8570),     # Holkar Indore
    62: (32.2190, 76.3230),     # HPCA Dharamsala
    63: (28.6377, 77.2432),     # Arun Jaitley Delhi
    839: (28.5670, 77.1030),    # Palam A Ground Delhi
    64: (22.5645, 88.3433),     # Eden Gardens
    65: (20.4620, 85.8830),     # Barabati Cuttack
    134: (26.1440, 91.7360),    # Barsapara Guwahati
    140: (17.7200, 83.2240),    # ACA-VDCA Vizag
    155: (18.9389, 72.8258),    # Brabourne Mumbai
    164: (8.5240, 76.9360),     # Greenfield Trivandrum
    170: (26.8500, 80.9500),    # Ekana Lucknow
    182: (23.0915, 72.5975),    # Narendra Modi Ahmedabad
    203: (21.2510, 81.6290),    # Shaheed Veer Narayan Raipur
    212: (26.4490, 80.3320),    # Green Park Kanpur
    365: (30.3160, 78.0320),    # Rajiv Gandhi Dehradun
    447: (10.3620, 77.9690),    # NPR Dindigul
    450: (8.7300, 77.7600),     # Indian Cement Tirunelveli
    468: (12.2960, 76.6390),    # Srikantadatta Mysore
    516: (26.8500, 80.9500),    # Ekana B ground
    549: (28.4740, 77.5360),    # Greater Noida
    681: (18.1100, 83.4200),    # PVG Raju Vizianagaram
    684: (14.6810, 77.6000),    # RDT Anantapur
    690: (11.9410, 79.8080),    # CAP Puducherry
    696: (13.0700, 77.5800),    # KSCA Alur
    699: (13.0700, 77.5800),    # KSCA 3
    702: (13.0700, 77.5800),    # KSCA 2
    705: (22.5200, 88.3700),    # Jadavpur Kolkata
    708: (22.3080, 73.1810),    # FB Colony Vadodara
    711: (22.3080, 73.1810),    # Moti Bagh Vadodara
    714: (22.7190, 75.8570),    # Emerald Indore
    717: (19.0600, 72.8670),    # BKC Mumbai
    720: (13.0400, 80.2300),    # Guru Nanak Chennai
    723: (13.0400, 80.2300),    # TI Cycles
    726: (13.0400, 80.2300),    # Sri Ramachandra Chennai
    729: (12.8700, 80.2200),    # SSN Chennai
    732: (19.0400, 73.0200),    # DY Patil Navi Mumbai
    821: (28.4600, 77.0300),    # Gurgaon Sultanpur
    824: (16.4300, 80.5600),    # ACA Mangalagiri
    827: (16.4300, 80.5600),    # Anghara Mulapadu
    830: (29.9500, 76.4000),    # CH Bansi Lahli
    833: (26.1440, 91.7360),    # Nehru Guwahati
    848: (22.3080, 73.1810),    # Alembic Vadodara
    857: (20.4620, 85.8830),    # Vikash Cuttack
    860: (23.0915, 72.5975),    # Sardar Patel B Ahmedabad
    863: (22.3030, 70.8020),    # SCA C Rajkot
    866: (8.5240, 76.9360),     # St Xaviers Thumba
    869: (22.5200, 88.3700),    # Videocon Kolkata
    872: (22.5200, 88.3700),    # CCF Ballygunj
    875: (20.2960, 85.8240),    # Vikash Bhubaneswar
    878: (13.0400, 80.2300),    # IIT Chemplast Chennai
    881: (23.0915, 72.5975),    # Modi A Ahmedabad
    902: (12.9788, 77.5996),    # Just Cricket Bengaluru
    911: (11.0160, 76.9560),    # SNR Coimbatore
    923: (11.6640, 78.1460),    # SCF Salem
    950: (26.9160, 75.7870),    # Jaipuria Jaipur
    953: (26.8500, 80.9500),    # Ekana B Lucknow
    956: (22.7190, 75.8570),    # Daly College Indore
    959: (30.6900, 76.7370),    # Maharaja Yadavindra Mullanpur
    962: (26.9160, 75.7870),    # KL Saini Jaipur
    980: (27.0400, 88.4700),    # SICA Rangpo
    983: (25.9100, 93.7300),    # Nagaland Dimapur
    986: (25.5940, 85.1370),    # Urja Patna
    989: (23.8310, 91.2860),    # Maharaja Bir Bikram Agartala
    995: (32.7260, 74.8570),    # JKCA Jammu
    998: (11.9410, 79.8080),    # CAP 2 Puducherry
    1001: (15.5000, 73.8300),   # Goa Academy Porvorim
    1004: (22.6900, 72.8700),  # Kheda Nadiad
    1010: (25.5780, 91.8930),  # Meghalaya Shillong
    1013: (22.8050, 86.2030),  # Keenan Jamshedpur
    1016: (22.3080, 73.1810),  # GSFC Vadodara
    1019: (23.0220, 72.5710),  # Gujarat College Ahmedabad
    1022: (28.6377, 77.2432),  # Karnail Singh Delhi
    1025: (22.5500, 72.9300),  # Lal Bahadur Anand
    1028: (30.3160, 78.0320),  # Abhimanyu Dehradun
    1031: (20.3500, 85.8200),  # DRIEMS Cuttack
    1034: (22.5500, 72.9300),  # Shastri Anand
    1037: (21.1700, 72.8300),  # Lalabhai Surat
    1040: (18.6740, 73.8060),  # DY Patil Ambi
    1043: (26.1440, 91.7360),  # Amingaon Guwahati
    1046: (30.6900, 76.7370),  # Sector 16 Chandigarh
    1049: (31.4700, 76.2700),  # Atal Bihari Nadaun
    1055: (22.9750, 88.4340),  # Bengal Academy Kalyani
    1058: (26.2380, 73.0240),  # Barkatullah Jodhpur
    1061: (25.5940, 85.1370),  # Moin-ul-Haq Patna
    1139: (30.3160, 78.0320),  # Kasiga Dehradun
    1142: (23.3560, 85.3250),  # JSCA Oval Ranchi
    1145: (19.0600, 72.8670),  # Sharad Pawar BKC
    1154: (30.3160, 78.0320),  # Maharana Pratap Dehradun
    1166: (32.7260, 74.8570),  # Molana Azad Jammu
    1169: (34.0830, 74.7970),  # Sher-i-Kashmir Srinagar
    1175: (17.6590, 75.9060),  # Indira Gandhi Solapur
    1178: (9.4980, 76.3380),   # SD College Alappuzha
    1181: (20.6100, 72.9300),  # Sardar Patel Valsad
    1184: (15.3640, 75.1240),  # KSCA Hubli
    1187: (22.5500, 72.9300),  # ADSA Railways Anand
    1190: (22.6900, 72.8700),  # GS Patel Nadiad
    1193: (27.4720, 94.9120),  # Jalan Dibrugarh
    1196: (17.4065, 78.5505),  # NexGen Hyderabad
    1199: (28.9840, 77.7060),  # Victoria Meerut
    1202: (22.3080, 73.1810),  # Kotambi Vadodara
    1208: (26.5000, 92.0300),  # Mangaldoi
    1211: (22.3030, 70.8020),  # Sanosara A Rajkot
    1214: (28.6377, 77.2432),  # Jamia Delhi
    1277: (26.2180, 78.1820),  # New Madhavrao Gwalior
    1278: (34.0830, 74.7970),  # Bakshi Srinagar
    1279: (30.6900, 76.7370),  # GMSSS Chandigarh
    1280: (26.8500, 80.9500),  # Sports Galaxy Lucknow
    1283: (22.6900, 72.8700),  # Gokulbhai Nadiad
    1284: (15.5000, 73.8300),  # Bhausaheb Goa
    1285: (19.8760, 75.3430),  # Chhatrapati Aurangabad
    1297: (17.4065, 78.5505),  # Gymkhana Hyderabad
    1300: (22.3030, 70.8020),  # Niranjan Shah C Rajkot
    1303: (22.3030, 70.8020),  # Madhavrao Rajkot
    1311: (19.9970, 73.7900),  # Golf Club Nasik
    1312: (23.0915, 72.5975),  # Modi B Ahmedabad
    1313: (25.3200, 74.6200),  # Miraj Upli Odan
    1330: (12.9788, 77.5996),  # BCCI CoE Bengaluru
    1331: (12.9788, 77.5996),  # BCCI CoE B
    1335: (25.0700, 73.8800),  # Madan Paliwal Rajsamand
    1336: (21.1700, 72.8300),  # Pithwala Surat
    1337: (27.4900, 95.3600),  # Tinsukia
    1338: (29.3900, 79.1300),  # Kaushiki Ramnagar
    1339: (13.9300, 75.5700),  # KSCA Shimoga
    1340: (8.5240, 76.9360),   # KCA Mangalapuram
    1343: (17.7200, 83.2240),  # ACA-VDCA Vizag
    1344: (20.2960, 85.8240),  # KIIT Bhubaneswar
    1345: (18.5200, 73.8560),  # Deccan Pune
    1346: (18.5200, 73.8560),  # Veerangan Pune
    1347: (22.3030, 70.8020),  # Sanosara B Rajkot
    1348: (26.9160, 75.7870),  # Anantam Jaipur
    1349: (23.3560, 85.3250),  # Usha Martin Ranchi
    1350: (26.9160, 75.7870),  # Dr Soni Jaipur
    1352: (26.1440, 91.7360),  # ACA Fulung Guwahati
    1353: (15.5000, 73.8300),  # 1919 Sportz Goa
    1355: (11.0160, 76.9560),  # Sri Ramakrishna Coimbatore
    1356: (31.6340, 74.8720),  # Gandhi Amritsar
    1357: (26.2180, 78.1820),  # Captain Roop Gwalior
    1358: (29.2180, 79.5280),  # Indira Gandhi Haldwani
    1342: (28.8900, 76.6400),  # Ch Bansi Rohtak
    1127: (11.9410, 79.8080),  # CAP 3 Puducherry
    1273: (14.6810, 77.6000),  # RDT B Anantapur

    # --- Ireland / Northern Ireland ---
    66: (53.2980, -6.2280),     # The Village Dublin
    67: (54.5766, -5.9544),     # Civil Service Belfast
    269: (53.2980, -6.2280),    # Castle Avenue Dublin
    403: (53.2980, -6.2280),    # Clontarf (Durbin typo)
    435: (54.8700, -7.3800),    # Bready
    893: (53.2980, -6.2280),    # Pembroke Dublin

    # --- New Zealand ---
    68: (-41.2880, 174.7860),   # Sky Stadium Wellington
    69: (-45.8700, 170.5100),   # University Oval Dunedin
    70: (-37.7850, 175.2830),   # Seddon Park Hamilton
    71: (-41.2700, 173.2830),   # Saxton Nelson
    72: (-45.0310, 168.6620),   # Queenstown Events
    73: (-39.0570, 174.0750),   # Pukekura New Plymouth
    74: (-38.6870, 176.0700),   # Owen Delany Taupo
    75: (-39.4920, 176.9180),   # McLean Park Napier
    76: (-43.5340, 172.6340),   # Hagley Christchurch
    77: (-36.8750, 174.7440),   # Eden Park Auckland
    78: (-35.7200, 174.3200),   # Cobham Whangarei
    79: (-45.8700, 170.5100),   # Carisbrook Dunedin
    80: (-43.6400, 172.4660),   # Bert Sutcliffe Lincoln
    81: (-37.6750, 176.2200),   # Bay Oval Mount Maunganui
    82: (-41.3000, 174.7800),   # Basin Reserve Wellington
    83: (-43.5340, 172.6340),   # AMI Christchurch
    176: (-39.0570, 174.0750),  # Yarrow New Plymouth
    179: (-36.8750, 174.7440),  # Eden Park Outer
    206: (-43.3040, 172.5980),  # Mainpower Rangiora
    209: (-46.4130, 168.3530),  # Queen's Park Invercargill
    513: (-40.3520, 175.6170),  # Fitzherbert Palmerston North
    519: (-43.6400, 172.4660),  # Lincoln No 3
    546: (-36.8750, 174.7440),  # Colin Maiden Auckland
    845: (-45.0310, 168.6620),  # John Davies Queenstown
    1304: (-36.8750, 174.7440), # Kennards Auckland
    1307: (-41.3000, 174.7800), # Cello Basin Wellington
    1308: (-45.8700, 170.5100), # Otago Oval Dunedin

    # --- Pakistan ---
    84: (33.6540, 73.0450),    # Rawalpindi
    85: (34.0150, 71.5800),     # Peshawar Club
    86: (30.1980, 71.4680),     # Multan
    87: (32.4940, 74.5220),     # Jinnah Sialkot
    88: (31.4180, 73.0890),     # Iqbal Faisalabad
    89: (31.5130, 74.3330),     # Gaddafi Lahore
    90: (30.1800, 66.9750),     # Bugti Quetta
    91: (29.3950, 71.6820),     # Bahawalpur
    173: (24.8600, 67.0100),    # National Karachi
    483: (34.1680, 73.2420),    # Abbottabad
    486: (24.8600, 67.0100),    # UBL Karachi
    495: (33.6540, 73.0450),    # KRL Rawalpindi
    522: (24.8600, 67.0100),    # NBP Karachi
    525: (24.8600, 67.0100),    # SBP Karachi
    678: (33.6540, 73.0450),    # Pindi Club
    884: (33.6540, 73.0450),    # House of Northern Islamabad
    887: (31.5130, 74.3330),    # LCCA Lahore
    890: (24.8600, 67.0100),    # Southend Karachi
    968: (31.5130, 74.3330),    # LCCA Lahore dup
    1136: (33.6540, 73.0450),   # Shoaib Akhtar Rawalpindi
    1157: (24.8600, 67.0100),   # National Bank Karachi
    1163: (24.8600, 67.0100),   # HPC Karachi
    1286: (33.6540, 73.0450),   # Diamond Islamabad
    1287: (33.6540, 73.0450),   # National Islamabad
    1288: (33.6540, 73.0450),   # Marghzar Islamabad
    1289: (34.1450, 71.7420),   # Ashfaq Charsadda
    1290: (32.1620, 74.1880),   # Jinnah Gujranwala
    1291: (31.5130, 74.3330),   # Saeed Sports Lahore
    1292: (31.7150, 73.9780),   # Rana Naveed Sheikhupura
    1294: (34.1200, 72.4700),   # Gohati Swabi
    1295: (33.8000, 72.9300),   # Railway Haripur
    1334: (34.0150, 71.5800),   # Imran Khan Peshawar

    # --- South Africa ---
    92: (-26.1880, 28.3200),    # Willowmoore Benoni
    93: (-26.1310, 28.0170),    # Wanderers Johannesburg
    94: (-25.8590, 28.1950),    # SuperSport Centurion
    95: (-33.9630, 25.6020),    # St George's PE
    96: (-26.7100, 27.1000),    # Senwes Potchefstroom
    97: (-26.1310, 28.0170),    # Old Wanderers
    98: (-33.9783, 18.4278),    # Newlands Cape Town
    99: (-29.8580, 31.0210),    # Moses Mabhida Durban
    100: (-29.1160, 26.2150),   # Mangaung Bloemfontein
    101: (-29.8580, 31.0210),   # Kingsmead Durban
    102: (-26.1950, 28.0590),   # Ellis Park
    103: (-28.7380, 24.7660),   # Diamond Kimberley
    104: (-32.9900, 27.9140),   # Buffalo East London
    105: (-33.7340, 18.9660),   # Boland Paarl
    356: (-29.6000, 30.3790),   # City Oval Pietermaritzburg
    362: (-33.5900, 22.2000),   # Recreation Oudtshoorn
    477: (-29.8580, 31.0210),   # Chatsworth Durban
    528: (-26.1310, 28.0170),   # New Wanderers
    534: (-26.7100, 27.1000),   # NWU Potchefstroom
    537: (-28.7380, 24.7660),   # Country Club Kimberley
    540: (-26.7100, 27.1000),   # Witrand Potchefstroom
    543: (-26.7100, 27.1000),   # NWU 2 Potchefstroom
    1052: (-26.1880, 28.3200),  # Willowmoore B
    1172: (-26.1310, 28.0170),  # Old Edwardians Joburg
    1205: (-33.9630, 25.6020),  # St George's Gqeberha
    1305: (-33.9783, 18.4278),  # WPCC Cape Town
    1306: (-33.9340, 18.8600),  # Paul Roos Stellenbosch

    # --- Sri Lanka ---
    106: (6.7730, 79.8820),     # Tyronne Moratuwa
    107: (6.9140, 79.8730),     # SSC Colombo
    108: (7.6730, 80.6490),     # Dambulla
    109: (6.9344, 79.8779),     # R Premadasa
    110: (7.2800, 80.6350),     # Pallekele
    111: (6.9140, 79.8730),     # P Sara
    112: (6.1240, 81.1180),     # Mahinda Rajapaksa Hambantota
    113: (6.0310, 80.2170),     # Galle
    114: (6.9140, 79.8730),     # CCC Colombo
    115: (7.2930, 80.6350),     # Asgiriya Kandy
    474: (6.9140, 79.8730),     # MCA Colombo
    480: (7.1800, 79.8800),     # Free Trade Zone Katunayake
    1320: (6.9140, 79.8730),    # Colts Colombo

    # --- West Indies ---
    116: (15.3010, -61.3880),   # Windsor Park Dominica
    117: (17.3020, -62.7170),   # Warner Park St Kitts
    118: (17.1050, -61.7900),   # Sir Viv Richards Antigua
    119: (18.0020, -76.7900),   # Sabina Park Jamaica
    120: (10.6600, -61.5200),   # Queen's Park Trinidad
    121: (6.8010, -58.1680),    # Providence Guyana
    122: (12.0500, -61.7500),   # National Grenada
    123: (13.1050, -59.6200),   # Kensington Barbados
    124: (14.0700, -60.9500),   # Darren Sammy St Lucia
    125: (17.1200, -61.8500),   # Antigua Recreation
    299: (10.2900, -61.4500),   # Brian Lara Tarouba
    329: (13.1300, -59.6200),   # Three Ws Cave Hill
    504: (17.3020, -62.7170),   # Conaree Basseterre
    531: (17.0040, -61.7720),   # Coolidge Antigua
    561: (13.1500, -61.2000),   # Arnos Vale SVG
    851: (6.8010, -58.1680),    # Everest Georgetown
    854: (10.7200, -61.5300),   # Diego Martin
    1293: (10.6600, -61.5200),  # Frank Worrell St Augustine
    1354: (19.2900, -81.3800),  # Jimmy Powell Cayman

    # --- Zimbabwe ---
    126: (-20.1500, 28.5800),   # Queens Bulawayo
    127: (-17.8250, 31.0500),   # Old Hararians
    128: (-18.9700, 29.8200),   # Kwekwe
    129: (-17.8250, 31.0500),   # Harare Sports Club
    130: (-20.1500, 28.5800),   # BAC Bulawayo
    359: (-18.9700, 29.8200),   # Mutare
    368: (-17.8250, 31.0500),   # Takashinga Harare
    842: (-20.0700, 30.8300),   # Masvingo

    # --- UAE ---
    131: (25.0466, 55.2191),    # Dubai International
    132: (24.3970, 54.5470),    # Sheikh Zayed Abu Dhabi
    133: (25.3243, 55.4209),    # Sharjah
    266: (25.0466, 55.2191),    # ICC Academy Dubai
    498: (25.0466, 55.2191),    # ICC Academy 2
    501: (24.3970, 54.5470),    # Tolerance Abu Dhabi
    812: (24.3970, 54.5470),    # Sheikh Zayed Nursery 2
    815: (25.0466, 55.2191),    # The Sevens Dubai
    1091: (25.3243, 55.4209),   # Malek Ajman
    1282: (25.3243, 55.4209),   # Seven Districts Ajman

    # --- Oman ---
    353: (23.5700, 58.3900),    # Al Amerat Turf 1
    794: (23.5700, 58.3900),    # Al Amerat Turf 2

    # --- USA / Canada / Americas ---
    135: (43.9500, -79.4600),   # Maple Leaf King City
    161: (26.1400, -80.2000),   # Central Broward Lauderhill
    444: (43.7170, -79.6500),   # CAA Brampton
    896: (29.5400, -95.3200),   # Moosa Pearland TX
    905: (29.7600, -95.6400),   # Prairie View Houston
    1106: (32.7450, -97.0900),  # Grand Prairie Dallas
    1109: (35.8400, -78.8400),  # Church Street Morrisville NC
    1220: (40.7300, -73.5900),  # Nassau County NY
    1316: (37.7510, -122.2010), # Oakland Coliseum
    1333: (49.2770, -123.1080), # BC Place Vancouver
    1064: (-34.5700, -58.4200), # Hurlingham Buenos Aires
    1070: (-34.5700, -58.4200), # Belgrano Buenos Aires
    1301: (-34.5700, -58.4200), # St George's Buenos Aires
    1302: (-34.5700, -58.4200), # St Albans Buenos Aires

    # --- Nepal ---
    347: (28.2100, 81.2500),    # SSP Dhangadi
    350: (28.2100, 81.2500),    # Fapla Dhangadi
    326: (27.6800, 85.2800),    # TU Kirtipur
    1076: (27.7100, 85.3200),   # Mulpani Kathmandu

    # --- Namibia ---
    376: (-22.5600, 17.0830),   # Wanderers Windhoek
    379: (-22.5600, 17.0830),   # United Windhoek
    382: (-22.5600, 17.0830),   # Affies Windhoek
    489: (-22.5600, 17.0830),   # Affies dup
    1315: (-22.5600, 17.0830),  # Namibia Ground
    1351: (-22.5600, 17.0830),  # High Performance Windhoek

    # --- Netherlands / Belgium / Luxembourg ---
    388: (52.2900, 4.8500),     # VRA Amstelveen
    397: (50.8500, 4.3500),     # Royal Brussels
    408: (52.0900, 5.1200),     # Maarschalkerweerd Utrecht
    417: (51.9200, 4.4800),     # Hazelaarweg Rotterdam
    420: (52.2500, 6.1600),     # Het Schootsveld Deventer
    453: (52.0800, 4.3100),     # Westvliet Hague
    636: (49.6600, 6.1300),     # Pierre Werner Luxembourg
    639: (51.0500, 3.7200),     # Belgian Oval Gent
    908: (51.0500, 3.7200),     # Meersen Gent
    935: (51.0300, 4.4800),     # Vrijbroek Mechelen
    1234: (51.9200, 4.4800),    # Sportpark Harga
    1255: (52.0800, 4.3100),    # Duivesteijn Voorburg

    # --- Europe (ECS, associate) ---
    371: (37.6020, -0.9800),    # La Manga Cartagena
    441: (55.6400, 12.0800),    # Svanholm Brondby
    459: (60.4000, 25.1000),    # Kerava Finland
    471: (44.5500, 26.0800),    # Moara Vlasiei Romania
    552: (36.8400, -2.4600),    # Desert Springs Almeria
    585: (60.2900, 25.0400),    # Tikkurila Vantaa
    588: (53.6500, 10.0000),    # Kummerfeld Germany
    591: (50.1060, 14.5230),    # Vinor Prague
    594: (52.3700, 9.7400),     # MTV Herrenhausen Hannover
    597: (59.3300, 18.0700),    # Marsta Stockholm
    600: (50.1060, 14.5230),    # Velvary Prague
    603: (47.4200, 9.3700),     # Grundenmoos St Gallen
    609: (50.1060, 14.5230),    # Scott Page Prague
    612: (49.1950, 16.6080),    # Brno
    615: (59.3300, 18.0700),    # Karsby Stockholm
    618: (57.7200, 12.0000),    # Kviberg Gothenburg
    621: (50.1100, 8.6820),     # Frankfurt CC
    624: (34.6800, 33.0400),    # Ypsonas Cyprus
    627: (59.4370, 24.7530),    # Tallinn Estonia
    633: (51.0500, 13.7400),    # Ostrapark Dresden
    642: (48.2500, 16.5200),    # Seebarn Austria
    645: (47.6800, 19.2500),    # GB Oval Szodliget Hungary
    648: (41.8340, 12.5940),    # Roma Capannelle
    651: (42.6970, 23.3220),    # Vasil Levski Sofia
    657: (39.1600, -8.9900),    # Cartaxo Portugal
    660: (51.9200, 4.5800),     # Sportpark Bermweg Capelle
    666: (50.1100, 8.6820),     # Frankfurt Oval
    669: (41.3850, 2.1730),     # Vic Barcelona
    675: (41.3640, 2.1550),     # Montjuic Barcelona
    687: (41.8000, 12.4500),    # Roma Spinaceto
    693: (35.8900, 14.4900),    # Marsa Malta
    734: (44.4680, 11.3580),    # Oval Rastignano Bologna
    746: (45.4400, 12.3200),    # Venezia
    749: (45.4640, 9.1900),     # Milan
    752: (40.2100, -8.4200),    # Miranda do Corvo
    755: (45.5400, 10.2200),    # JCC Brescia
    764: (51.3400, 6.5600),     # Bayer Krefeld
    767: (54.3200, 10.1400),    # Kiel
    779: (36.7100, -4.6200),    # Cartama Spain
    782: (59.3300, 18.0700),    # Norsborg Stockholm
    788: (51.0500, 13.7400),    # Rugby Dresden
    791: (40.6900, -8.4800),    # Gucherre Albergaria
    818: (38.3500, -0.4800),    # Sporting Alfas Alicante
    836: (41.8340, 12.5940),    # Roma Cricket
    917: (44.8170, 20.4630),    # Lisicji Jarak Belgrade
    947: (45.8150, 15.9820),    # Budenec Zagreb
    1088: (42.6970, 23.3220),   # Vasil Levski dup
    1151: (45.8150, 15.9820),   # Mladost Zagreb
    1231: (45.5400, 10.2200),   # ASD Jinnah Brescia
    1237: (41.8340, 12.5940),    # Simar Roma
    1243: (46.0500, 14.5050),   # Valburga Ljubljana
    1314: (40.6900, -8.4800),   # Santarem Albergaria
    1319: (44.4680, 11.3580),   # Fabio Fabbri Bologna
    1322: (50.9700, 4.4700),    # Stars Arena Hofstade Belgium
    1324: (51.3400, 6.5600),    # Krefeld 1905
    1325: (59.3300, 18.0700),   # Botkyrka Stockholm
    1359: (55.6760, 12.5680),   # Solvangs Copenhagen
    1360: (35.1700, 137.0500),  # Korogi Nisshin Japan

    # --- Scotland / Wales / Channel Islands ---
    394: (55.9600, -3.2100),    # Grange Edinburgh
    400: (51.5900, -2.9900),    # Newport Wales
    405: (50.7000, -1.2900),    # Newclose Isle of Wight
    411: (49.4600, -2.5400),    # College Field Guernsey
    1270: (49.4600, -2.5400),   # Guernsey Rovers

    # --- Malaysia / Singapore / East Asia ---
    429: (3.1400, 101.6900),    # Kinrara KL
    462: (32.2940, -64.7840),   # White Hill Bermuda
    465: (32.2940, -64.7840),   # National Hamilton Bermuda
    492: (1.3520, 103.8200),    # Indian Association Singapore
    992: (3.1400, 101.6900),    # Bayuemas KL
    1007: (2.9400, 101.7800),   # UKM-YSD Bangi
    1073: (13.7560, 100.5020),  # Terdthai Bangkok
    1267: (3.1400, 101.6900),   # Selangor Turf KL
    1271: (2.9400, 101.7800),   # YSD-UKM Bangi
    1276: (37.4600, 126.6700),  # Yeonhui Incheon
    1309: (1.4900, 103.7600),   # Johor
    1310: (1.5500, 110.3400),   # Borneo Sarawak
    944: (35.5800, 139.4300),   # Sano Japan
    1085: (35.5800, 139.4300),  # Sano 2 Japan

    # --- Kenya / Africa associate ---
    555: (-1.2920, 36.8220),    # Gymkhana Nairobi
    1249: (-1.2920, 36.8220),   # Sikh Union Nairobi
    1281: (-1.2920, 36.8220),   # Ruaraka Nairobi
    965: (-6.7920, 39.2080),    # Annadil Dar-es-Salaam
    1274: (-6.7920, 39.2080),   # UDSM Dar-es-Salaam
    1275: (-6.7920, 39.2080),   # Gymkhana Dar-es-Salaam
    974: (-1.9500, 30.0600),    # Gahanga Kigali
    977: (-1.9500, 30.0600),    # IPRC Kigali
    1298: (6.4550, 3.3940),     # Tafawa Balewa Lagos
    1299: (6.4550, 3.3940),     # University Lagos
    1226: (5.6030, -0.1870),    # Achimota A Accra
    1229: (5.6030, -0.1870),    # Achimota B Accra
    1363: (-24.6280, 25.9230),  # Botswana 1 Gaborone
    1364: (-24.6280, 25.9230),  # Botswana 2 Gaborone
    1323: (-15.7860, 35.0050),  # TCA Blantyre Malawi

    # --- Qatar / Afghanistan / Middle East ---
    438: (25.3200, 51.4400),    # West End Doha
    654: (34.5550, 69.2070),    # Kabul
    1296: (25.3200, 51.4400),   # UDST Doha
    1321: (36.7280, 68.8670),   # Kunduz

    # --- Hong Kong / Pacific ---
    1067: (22.3200, 114.1700),  # Mission Road HK
    1317: (22.3200, 114.1700),  # Tin Kwong HK
    558: (-17.7330, 168.3270),  # Vanuatu
    929: (-9.4780, 147.1500),   # Amini Port Moresby
    938: (-17.7330, 168.3270),  # Independence Port Vila
    1264: (-13.8330, -171.7500),# Faleata Apia

    # --- Gibraltar / Cyprus / misc ---
    1079: (36.1400, -5.3500),   # Europa Gibraltar
    803: (34.6700, 32.8700),    # Happy Valley Episkopi Cyprus
    806: (45.1000, 15.2000),    # Croatia generic
    809: (43.5100, 16.4400),    # Hotel Resnik Croatia
    1362: (34.6700, 32.8700),   # Happy Valley 2

    # --- Jersey / Isle of Man ---
    899: (49.1800, -2.1100),    # King George V Jersey
    1112: (49.1800, -2.1100),   # Farmers St Martin
    1115: (54.1500, -4.4800),   # King William's Castletown

    # --- Misc UK duplicates / aliases ---
    663: (52.9140, -1.4580),    # County Ground Derby
    40: (52.2480, -0.8710),     # Northampton (dup id 40)
}
# fmt: on


def main() -> None:
    import json
    from pathlib import Path

    api_path = ROOT / "data" / "_venues_api.json"
    venues = json.loads(api_path.read_text(encoding="utf-8"))
    api_ids = {v["id"] for v in venues}

    by_id = {str(k): {"lat": v[0], "lon": v[1]} for k, v in COORDS.items()}
    by_name = {
        "lords": {"lat": 51.5294, "lon": -0.1727},
        "kennington oval": {"lat": 51.4821, "lon": -0.1117},
        "the oval": {"lat": 51.4821, "lon": -0.1117},
        "m a chidambaram stadium": {"lat": 13.0627, "lon": 80.2792},
        "ma chidambaram stadium": {"lat": 13.0627, "lon": 80.2792},
        "m chinnaswamy stadium": {"lat": 12.9788, "lon": 77.5996},
        "eden gardens": {"lat": 22.5645, "lon": 88.3433},
        "wankhede stadium": {"lat": 18.9389, "lon": 72.8258},
        "narendra modi stadium": {"lat": 23.0915, "lon": 72.5975},
        "melbourne cricket ground": {"lat": -37.8200, "lon": 144.9834},
        "sydney cricket ground": {"lat": -33.8917, "lon": 151.2247},
        "the gabba": {"lat": -27.4858, "lon": 153.0381},
        "brisbane cricket ground": {"lat": -27.4858, "lon": 153.0381},
        "dubai international cricket stadium": {"lat": 25.0466, "lon": 55.2191},
        "sharjah cricket stadium": {"lat": 25.3243, "lon": 55.4209},
        "sheikh zayed stadium": {"lat": 24.3970, "lon": 54.5470},
        "r premadasa stadium": {"lat": 6.9344, "lon": 79.8779},
        "newlands": {"lat": -33.9783, "lon": 18.4278},
    }

    missing = sorted(api_ids - set(COORDS.keys()))
    extra = sorted(set(COORDS.keys()) - api_ids)

    seed = {"by_id": by_id, "by_name": by_name, "_missing_api_ids": missing, "_extra_ids": extra}
    OUT.write_text(json.dumps(seed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"COORDS entries : {len(COORDS)}")
    print(f"API venues     : {len(api_ids)}")
    print(f"Missing from seed: {len(missing)}")
    if missing:
        print("  ", missing[:30], "..." if len(missing) > 30 else "")
    if extra:
        print(f"Extra (not in API): {extra}")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
