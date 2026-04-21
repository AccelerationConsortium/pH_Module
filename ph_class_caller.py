from ph_analyzer_new_5_8range import PHAnalyzer

analyzer = PHAnalyzer()

# Uncomment to print live camera metadata to terminal

analyzer.read_ph()
analyzer.dispense_strip()
#analyzer.get_metadata()

'''
# Full workflow
with PHAnalyzer() as analyzer:
    analyzer.dispense_strip()
    ph = analyzer.read_ph()
    print(f"pH: {ph}")
'''

