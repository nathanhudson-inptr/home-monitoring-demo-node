#Python Docker image, Slim - minumum distribution. bookworm - Debian 12 "Bookworm"
FROM python:3.12-slim

#Create working directory
WORKDIR /code

#Copy requirements.txt to /code (WORKDIR)
COPY ./requirements.txt ./
#Install requirements using pip. --no-cache-dir -
RUN pip install --no-cache-dir -r requirements.txt

COPY ./src ./src

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "80", "--reload"]