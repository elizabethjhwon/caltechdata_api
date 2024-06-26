import argparse, os, json
import s3fs
import requests
from datacite import schema43, DataCiteRESTClient
from caltechdata_api import caltechdata_write, caltechdata_edit
from tqdm import tqdm

folder = "0_gregoire"

endpoint = "https://renc.osn.xsede.org/"

# Get metadata and files from bucket
s3 = s3fs.S3FileSystem(anon=True, client_kwargs={"endpoint_url": endpoint})

# Set up datacite client
password = os.environ["DATACITE"]
prefix = "10.25989"
datacite = DataCiteRESTClient(username="CALTECH.HTE", password=password, prefix=prefix)

path = "ini210004tommorrell/" + folder + "/"
dirs = s3.ls(path)
# Strip out reference to top level directory
repeat = dirs.pop(0)
assert repeat == path
# Switch directories to doi
records = []
for record in dirs:
    body = record.split("0_gregoire/")[1]
    records.append(f"{prefix}/{body}")

with open("new_ids.json", "r") as infile:
    record_ids = json.load(infile)

# We are using the list of unregistered dois
# with open("unregistered_dois.json", "r") as infile:
#    data = json.load(infile)
# records = data["pub"]

abstract = """This record is a component of the Materials Experiment and
Analysis Database (MEAD). It contains raw data and metadata from millions 
of materials synthesis and characterization experiments, as well as the 
analysis and distillation of that data into property and performance 
metrics. The unprecedented quantity and diversity of experimental data 
are searchable by experiment and analysis attributes generated by both 
researchers and data processing software.
"""

with open("completed_dois.json", "r") as infile:
    completed = json.load(infile)

for doi in completed:
    if doi in records:
        records.remove(doi)
    else:
        print(doi)

with open("excluded_dois.json", "r") as infile:
    excluded = json.load(infile)

for doi in excluded:
    records.remove(doi)

for record in tqdm(records):
    base = record.split("/")[1]
    meta_path = path + base + "/metadata.json"
    metadata = None
    files = s3.ls(path + base)
    if len(files) == 0:
        excluded.append(record)
        print(f"No files available {record}")
        with open("excluded_dois.json", "w") as outfile:
            data = json.dump(excluded, outfile)
    else:
        try:
            metaf = s3.open(meta_path, "rb")
            metadata = json.load(metaf)
        except:
            print(files)
            excluded.append(record)
            print(f"Missing metadata {record}")
            exit()
            with open("excluded_dois.json", "w") as outfile:
                data = json.dump(excluded, outfile)

    if metadata:
        metadata["identifiers"] = [{"identifier": record, "identifierType": "DOI"}]

        # Find the zip file or files
        zipf = s3.glob(path + base + "/*.zip")
        file_links = []

        description_string = f"Files available via S3 at {endpoint}{path}<br>"
        for link in zipf:
            fname = link.split("/")[-1]
            file_links.append(endpoint + link)

        metadata["types"] = {"resourceType": "", "resourceTypeGeneral": "Dataset"}
        metadata["schemaVersion"] = "http://datacite.org/schema/kernel-4"
        metadata["publicationYear"] = str(metadata["publicationYear"])
        metadata["rightsList"] = [
            {
                "rights": "cc-by-sa-4.0",
                "rightsUri": "http://creativecommons.org/licenses/by-sa/4.0/",
            }
        ]
        static = [
            {
                "relatedIdentifier": "10.25989/es8t-kswe",
                "relationType": "IsPartOf",
                "relatedIdentifierType": "DOI",
            },
            {
                "relatedIdentifier": "10.1038/s41524-019-0216-x",
                "relationType": "IsDocumentedBy",
                "relatedIdentifierType": "DOI",
            },
        ]
        if "relatedIdentifiers" in metadata:
            metadata["relatedIdentifiers"] += static
        else:
            metadata["relatedIdentifiers"] = static
        metadata["fundingReferences"] = [
            {
                "funderName": "Office of Science of the U.S. Department of Energy",
                "awardTitle": "Energy Innovation Hub Renewal - Fuels from Sunlight",
                "awardNumber": "DE-SC0004993",
            }
        ]

        if "descriptions" not in metadata:
            metadata["descriptions"] = [
                {"description": abstract, "descriptionType": "Abstract"}
            ]
        else:
            print(metadata["descriptions"])
            exit()

        for meta in metadata.copy():
            if metadata[meta] == []:
                metadata.pop(meta)
        for contributor in metadata["contributors"]:
            if contributor["affiliation"] == []:
                contributor.pop("affiliation")
        new_cre = []
        for creator in metadata["creators"]:
            if creator["affiliation"] == []:
                creator.pop("affiliation")
            if creator["name"] != "Contributors":
                new_cre.append(creator)
        metadata["creators"] = new_cre

        doi = metadata["doi"].lower()
        unnecessary = [
            "id",
            "doi",
            "container",
            "providerId",
            "clientId",
            "agency",
            "state",
        ]
        for un in unnecessary:
            if un in metadata:
                metadata.pop(un)
        if "dates" in metadata:
            for d in metadata["dates"]:
                d["date"] = str(d["date"])
        valid = schema43.validate(metadata)
        if not valid:
            v = schema43.validator.validate(metadata)
            errors = sorted(v.iter_errors(instance), key=lambda e: e.path)
            for error in errors:
                print(error.message)
            exit()

        metadata.pop("language")
        community = "d0de1569-0a01-498f-b6bd-4bc75d54012f"

        production = True

        # We're now doing new records, so redirects are not needed
        # result = requests.get(f'https://api.datacite.org/dois/{doi}')
        # if result.status_code != 200:
        #    print('DATACITE Failed')
        #    print(result.text)
        #    exit()

        # url = result.json()['data']['attributes']['url']
        # old_id = url.split('data.caltech.edu/records/')[1]
        new_id = caltechdata_write(
            metadata,
            schema="43",
            publish=True,
            production=True,
            file_links=file_links,
            s3=s3,
            community=community,
        )
        url = f"https://data.caltech.edu/records/{new_id}"

        # record_ids[old_id] = new_id
        # with open("new_ids.json", "w") as outfile:
        #    json.dump(record_ids, outfile)

        result = requests.get(f"https://api.datacite.org/dois/{doi}")
        if result.status_code != 200:
            doi = datacite.public_doi(doi=record, metadata=metadata, url=url)
        else:
            doi = datacite.update_doi(doi=record, metadata=metadata, url=url)["doi"]
        completed.append(doi)
        with open("completed_dois.json", "w") as outfile:
            data = json.dump(completed, outfile)
