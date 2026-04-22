# Doctor Triage and Prescriptions Guide

## Purpose
This guide explains how doctors interact with patient triage records and how to create and manage prescriptions within the Doctor-Patient Appointment Management System.

## Triage Overview
- Triage is performed by a nurse before the patient enters the consultation room.
- Triage records the patient's vitals and initial symptoms before the doctor sees them.
- A doctor may view triage entries for their assigned patients but cannot create triage entries.
- Triage visibility is limited to the nurse, the assigned doctor, and admin.

## Triage Vitals Recorded
- Blood pressure (e.g. 120/80 mmHg)
- Heart rate (beats per minute, valid range 20–300)
- Body temperature in Celsius (valid range 30.0–45.0)
- Body weight in kilograms (valid range 0.5–500.0)
- Oxygen saturation as SpO2 percentage (0–100)
- Presenting symptoms (free text, up to 500 characters)
- Additional clinical notes (up to 500 characters)
- Queue type: normal or emergency

## Viewing Triage Data
- A doctor may retrieve all triage entries for a specific patient using the patient's ID.
- A doctor may also retrieve all triage entries recorded on a specific date, optionally filtered to their own patients.
- Triage data appears before the consultation to help the doctor prepare.

## Prescription Policy
- Only doctors may create prescriptions.
- A prescription must be linked to a specific appointment ID.
- The doctor may only create a prescription for an appointment assigned to that doctor.
- A prescription cannot be created for an appointment that does not exist.

## Prescription Contents
- Diagnosis: a written clinical finding (minimum 2 characters, maximum 1000 characters)
- Medicines: a list or description of prescribed medicines (minimum 2 characters, maximum 2000 characters)
- Advice: optional post-consultation instructions for the patient (up to 2000 characters)
- Follow-up date: optional date for the next visit

## Viewing Prescriptions
- A doctor may view all prescriptions they have created using their doctor ID.
- A doctor may not view prescriptions created by other doctors.
- Prescription records include the patient name, doctor name, specialization, diagnosis, medicines, advice, follow-up date, and creation timestamp.

## Prescription PDF and Drive Export
- Prescriptions can be exported as a PDF and saved to the hospital's Google Drive.
- When a prescription PDF is saved, the system automatically shares the file with the patient's registered email address.
- Patients will find the shared prescription PDF in the "Shared with me" section of their Google Drive.
- The doctor should advise the patient to check their registered email account's Google Drive after the consultation.

## Clinical Responsibility Policy
- The AI assistant does not create diagnoses or prescriptions.
- All prescription content is entered and approved by the doctor.
- Triage vitals are recorded by the nurse; the doctor reviews them as supporting information only.
- Doctors remain clinically responsible for all prescriptions issued under their account.
