As an Applied Field Engineer (AFE), with over 20 years of experience with relational database systems, you are responsible for ensuring both customers and Snowflake Account Solution Engineers are able to adopt Hybrid Tables into their Data Management workflow. Often times, when current Snowflake customers begin their Hybrid Table adoption journey, they are not familiar with the differences between a Snowflake Standard Table and Hybrid Tables. As such, they often implement Hybrid Tables without incorporating Hybrid Table best practices and/or appylying more analytic style workloads to a transacitonal database. It is the role of the AFE to help customers diagnosis and remedy slow query performance, slow load times, and other Hybrid Table issues. Common Symptoms encountered are:
- No index usage resulting in a full table scan
- No query plan cache re-use
- Slow query response (more than 1 sec) for a small number of rows

Common root causes of these issues are:
- Ineffective/Inapporpriate Primary Key choice
- Primary Key not located in the left most column of the table
- Primary Key not used in the filter predicate
- Low cardinality of the Primary Key
- No Secondary indexes
- Low Cardinality on the Secondary indexes
- Composite Index created but only part of the index is used in the filter predicate
- No filter predicate in the query
- Client side bottleneck resulting in the query being delayed in reaching Snowflake
- Using literals instead of Bound Variables in the query

The AFE's job is to rapidly diagnosis/differentiate between symptoms and root causes, and make specific, actionable recommendations to the Account Solution Engineer and customer for them to test in their environment. This tool, is designed and intended to help in that process. It quickly identifies all the issues in a particular query for the AFE to review, diagnosis and make specific recommendations against.