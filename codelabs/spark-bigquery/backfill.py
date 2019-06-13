# Copyright 2019 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


# This code accompanies the codelab <NAME>. It contains a script for backfilling a set of data 

# Basic Python Imports
import re
import time
import sys

# A Spark Session is how we interact with Spark SQL to create Dataframes
from pyspark.sql import SparkSession

# Library for interacting with Google Cloud Storage
from google.cloud import storage

# This will help catch some PySpark errors
from py4j.protocol import Py4JJavaError

# Create a SparkSession under the name "reddit". Viewable via the Spark UI
spark = SparkSession.builder.appName("reddit").getOrCreate()

# Establish a set of years and months to iterate over
year = sys.argv[1]
month = sys.argv[2]
          
# Establish a subreddit to process
subreddit = 'worldpolitics'

# Set Google Cloud Storage temp location          
bucket_name = "bm_reddit"
path = "tmp" + str(time.time())

# Keep track of all tables accessed via the job
tables_read = []
        
# In the form of <project-id>.<dataset>.<table>
table = f"fh-bigquery.reddit_posts.{year}_{month}"
        
# If the table doesn't exist we will simply continue and not
# log it into our "tables_read" list
try:
    df = spark.read.format('bigquery').option('table', table).load()
except Py4JJavaError:
   print(f"{table} does not exist. ") 
   sys.exit(0)        

print(f"Processing {table}.")

# Select the "body" and "created_utc" columns of the designated subreddit
subreddit_timestamps = (
    df
    .select("title", "selftext", "created_utc")
    .where(df.subreddit == subreddit)
)
        
tmp_output_path = "gs://" + bucket_name + "/" + path + "/" + year + "/" + month
# Write output to our temp GCS bucket. Spark jobs can be written out to multiple files 
# partitions.By using coalesce, we ensure the output is consolidated to a single file.
# We then use .options to tell Spark to write out in a gzip format, and .csv to do the write.
(
    subreddit_timestamps
    # Data can get written out to multiple files / partition. 
    # This ensures it will only write to 1.
    .coalesce(1) 
    .write
    # Gzip the output file
    .options(codec="org.apache.hadoop.io.compress.GzipCodec")
    # Write out to csv
    .csv(tmp_output_path)
)
# Lastly, we'll move the temp file to a new bucket and delete the temp directory.
regex = "part-[0-9a-zA-Z\-]*.csv.gz"
new_path = "/".join(["reddit_posts", year, month, subreddit + ".csv.gz"])
        
# Create the storage client
storage_client = storage.Client()
        
# Create an object representing the original bucket
source_bucket = storage_client.get_bucket(bucket_name)
        
# Grab all files in the source bucket. Typically there is also a _SUCCESS file, inside of the
# directory, so we'll make sure to find our single csv file.
buckets = list(source_bucket.list_blobs(prefix=path))
for bucket in buckets:
    name = bucket.name
            
    # Locate the file that represents our partition. Copy to new location and 
    # delete temp directory.
    if re.search(regex, name):
       blob = source_bucket.blob(name)
       source_bucket.copy_blob(blob, source_bucket, new_path)
       blob.delete()